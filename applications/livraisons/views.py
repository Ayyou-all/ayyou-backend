"""
Vues HTTP pour l'espace Livreur AYYOU.

Prend en charge :
- Consultation des courses disponibles et acceptation
- Navigation de mission étape par étape (guichet restaurant, trajet client)
- Pointage des articles emballés
- Clôture par code PIN de sécurité à 4 chiffres
- Suivi GPS et gestion de la disponibilité en ligne
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.commandes.models import Commande, StatutCommande
from applications.commandes.services import valider_reception_client_par_pin
from applications.communs.erreurs import ErreurMetier
from applications.utilisateurs.permissions import EstLivreur

from .models import DisponibiliteLivreur, EtapeLivraison, Livraison
from .serializers import (
    SerializerChangementDisponibilite,
    SerializerLivraisonEnCours,
    SerializerMiseAJourPosition,
    SerializerPointageArticle,
    SerializerProfilLivreur,
    SerializerPropositionLivraison,
)
from .services import (
    accepter_mission_livraison,
    demarrer_trajet_vers_client,
    lister_courses_disponibles,
    mettre_a_jour_position_gps,
    obtenir_profil_livreur,
    pointer_article_au_guichet,
    signaler_arrivee_domicile_client,
    valider_livraison_avec_pin,
)


class VuePropositionsCourses(APIView):
    """Liste des courses prêtes à être acceptées par un coursier disponible."""

    permission_classes = [EstLivreur]

    def get(self, request):
        profil = obtenir_profil_livreur(request.user)
        courses = lister_courses_disponibles(profil)
        return Response(SerializerPropositionLivraison(courses, many=True).data)


class VueAccepterMission(APIView):
    """Le coursier accepte la course dans les 30 secondes."""

    permission_classes = [EstLivreur]

    def post(self, request, commande_id):
        profil = obtenir_profil_livreur(request.user)
        if str(commande_id).isdigit():
            commande = Commande.objects.filter(pk=int(commande_id)).first()
        else:
            ref = str(commande_id).lstrip("#")
            commande = Commande.objects.filter(reference=ref).first()
            if not commande:
                commande = Commande.objects.filter(reference=commande_id).first()
        if not commande:
            commande = get_object_or_404(Commande, pk=commande_id)

        livraison = accepter_mission_livraison(commande, profil)
        return Response(SerializerLivraisonEnCours(livraison).data, status=status.HTTP_201_CREATED)


class VueMissionEnCours(APIView):
    """Détail de la course active actuellement prise en charge par le livreur."""

    permission_classes = [EstLivreur]

    def get(self, request):
        profil = obtenir_profil_livreur(request.user)
        livraison_active = (
            Livraison.objects.filter(livreur=profil)
            .exclude(etape__in=[EtapeLivraison.LIVREE, EtapeLivraison.ECHOUEE])
            .select_related("commande", "commande__etablissement", "commande__client")
            .prefetch_related("commande__lignes")
            .first()
        )
        if livraison_active is None:
            return Response({"mission_active": False, "message": "Aucune course active pour le moment."})

        return Response({"mission_active": True, "livraison": SerializerLivraisonEnCours(livraison_active).data})


class VuePointerArticle(APIView):
    """Le coursier coche un article au comptoir lors de la vérification."""

    permission_classes = [EstLivreur]

    def post(self, request):
        profil = obtenir_profil_livreur(request.user)
        serializer = SerializerPointageArticle(data=request.data)
        serializer.is_valid(raise_exception=True)

        livraison_active = Livraison.objects.filter(livreur=profil).exclude(etape=EtapeLivraison.LIVREE).first()
        if not livraison_active:
            raise ErreurMetier("Aucune livraison active.", code="aucune_livraison")

        ligne_maj = pointer_article_au_guichet(
            livraison=livraison_active,
            ligne_id=serializer.validated_data["ligne_id"],
            est_verifie=serializer.validated_data["est_verifie"],
        )
        return Response({"ligne_id": ligne_maj.id, "est_verifie": ligne_maj.est_verifie_par_livreur})


class VueDepartVersClient(APIView):
    """Le livreur quitte le restaurant avec les articles vérifiés."""

    permission_classes = [EstLivreur]

    def post(self, request):
        profil = obtenir_profil_livreur(request.user)
        livraison_active = Livraison.objects.filter(livreur=profil).exclude(etape=EtapeLivraison.LIVREE).first()
        if not livraison_active:
            raise ErreurMetier("Aucune livraison active.")

        demarrer_trajet_vers_client(livraison_active)
        return Response({"etape": livraison_active.etape, "message": "En route vers le client."})


class VueArriveeClient(APIView):
    """Le livreur signale son arrivée devant le domicile du client."""

    permission_classes = [EstLivreur]

    def post(self, request):
        profil = obtenir_profil_livreur(request.user)
        livraison_active = Livraison.objects.filter(livreur=profil).exclude(etape=EtapeLivraison.LIVREE).first()
        if not livraison_active:
            raise ErreurMetier("Aucune livraison active.")

        signaler_arrivee_domicile_client(livraison_active)
        return Response({"etape": livraison_active.etape, "message": "Arrivé devant l'adresse client."})


class VueCloturerLivraisonPin(APIView):
    """Le coursier saisit le code PIN donné par le client pour finaliser la livraison."""

    permission_classes = [EstLivreur]

    def post(self, request):
        profil = obtenir_profil_livreur(request.user)
        code_pin = request.data.get("code_pin", "")

        livraison_active = Livraison.objects.filter(livreur=profil).exclude(etape=EtapeLivraison.LIVREE).first()
        if not livraison_active:
            commande_ref = request.data.get("commande_reference") or request.data.get("commande_id")
            if commande_ref:
                ref = str(commande_ref).lstrip("#")
                commande = Commande.objects.filter(reference=ref).first()
                if not commande and str(commande_ref).isdigit():
                    commande = Commande.objects.filter(pk=int(commande_ref)).first()
                if commande and commande.statut != StatutCommande.LIVREE:
                    valider_reception_client_par_pin(commande, request.user, code_pin)
                    gain = max(int(commande.frais_livraison_fcfa * 0.8), 1000)
                    return Response(
                        {
                            "succes": True,
                            "message": "Livraison clôturée avec succès.",
                            "gain_fcfa": gain,
                        }
                    )
            raise ErreurMetier("Aucune livraison active.")

        valider_livraison_avec_pin(livraison_active, code_pin)
        return Response(
            {
                "succes": True,
                "message": "Livraison clôturée avec succès. Félicitations pour votre course !",
                "gain_fcfa": livraison_active.gain_livreur_fcfa,
            }
        )


class VuePositionGpsLivreur(APIView):
    """Mise à jour en continu de la géolocalisation pour le tracé Leaflet."""

    permission_classes = [EstLivreur]

    def post(self, request):
        return self.patch(request)

    def patch(self, request):
        profil = obtenir_profil_livreur(request.user)
        serializer = SerializerMiseAJourPosition(data=request.data)
        serializer.is_valid(raise_exception=True)

        lat = float(serializer.validated_data["latitude"])
        lng = float(serializer.validated_data["longitude"])

        mettre_a_jour_position_gps(
            profil_livreur=profil,
            latitude=lat,
            longitude=lng,
        )
        return Response({
            "succes": True,
            "latitude": lat,
            "longitude": lng,
            "date_derniere_position": profil.date_derniere_position.isoformat() if profil.date_derniere_position else None,
        })


class VueDisponibiliteLivreur(APIView):
    """Interrupteur En ligne / Hors ligne."""

    permission_classes = [EstLivreur]

    def post(self, request):
        return self.patch(request)

    def patch(self, request):
        profil = obtenir_profil_livreur(request.user)
        serializer = SerializerChangementDisponibilite(data=request.data)
        serializer.is_valid(raise_exception=True)

        profil.disponibilite = serializer.validated_data["disponibilite"]
        profil.save(update_fields=["disponibilite"])
        return Response({"disponibilite": profil.disponibilite})


from rest_framework.parsers import FormParser, JSONParser, MultiPartParser


class VueMonProfilLivreur(APIView):
    """Profil et statistiques de gains du jour."""

    permission_classes = [EstLivreur]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        profil = obtenir_profil_livreur(request.user)
        return Response(SerializerProfilLivreur(profil, context={"request": request}).data)

    def patch(self, request):
        profil = obtenir_profil_livreur(request.user)
        user = request.user
        data = request.data

        # 1. Mise à jour des informations personnelles de l'utilisateur
        utilisateur_modifie = False
        champs_utilisateur = {
            "prenom": data.get("prenom"),
            "nom": data.get("nom"),
            "telephone": data.get("telephone"),
            "adresse": data.get("adresse"),
        }
        for champ, valeur in champs_utilisateur.items():
            if valeur is not None:
                setattr(user, champ, str(valeur).strip())
                utilisateur_modifie = True

        # Mise à jour de la photo de profil
        if "photo" in request.FILES:
            user.photo = request.FILES["photo"]
            utilisateur_modifie = True

        # Mise à jour du mot de passe
        nouveau_mdp = data.get("nouveau_mot_de_passe") or data.get("nouveauMotDePasse") or data.get("mot_de_passe")
        if nouveau_mdp:
            nouveau_mdp = str(nouveau_mdp).strip()
            if len(nouveau_mdp) < 6:
                raise ErreurMetier("Le mot de passe doit comporter au moins 6 caractères.", code="mot_de_passe_court")

            ancien_mdp = data.get("ancien_mot_de_passe") or data.get("ancienMotDePasse")
            if ancien_mdp and not user.check_password(ancien_mdp):
                raise ErreurMetier("L'ancien mot de passe saisi est incorrect.", code="ancien_mot_de_passe_invalide")

            user.set_password(nouveau_mdp)
            utilisateur_modifie = True

        if utilisateur_modifie:
            user.save()

        # 2. Mise à jour des données spécifiques livreur (véhicule, immatriculation, zone)
        profil_modifie = False
        type_vehicule = data.get("type_vehicule") or data.get("typeVehicule")
        if type_vehicule:
            profil.type_vehicule = str(type_vehicule).upper().strip()
            profil_modifie = True

        nom_vehicule = data.get("nom_vehicule") or data.get("nomVehicule")
        if nom_vehicule is not None:
            profil.nom_vehicule = str(nom_vehicule).strip()
            profil_modifie = True

        immatriculation = data.get("immatriculation") or data.get("numeroPlaque")
        if immatriculation is not None:
            profil.immatriculation = str(immatriculation).strip()
            profil_modifie = True

        zone_principale = data.get("zone_principale") or data.get("zonePrincipale") or data.get("zoneActivite")
        if zone_principale is not None:
            profil.zone_principale = str(zone_principale).strip()
            profil_modifie = True

        if profil_modifie:
            profil.save()

        # 3. Téléversement éventuel de documents justificatifs (Permis recto / verso)
        from applications.utilisateurs.models import DocumentJustificatif, TypeDocument, StatutDocument
        if "permis_recto" in request.FILES:
            DocumentJustificatif.objects.create(
                proprietaire=user,
                type_document=TypeDocument.PERMIS_CONDUIRE,
                fichier=request.FILES["permis_recto"],
                statut=StatutDocument.EN_ATTENTE,
            )
        if "permis_verso" in request.FILES:
            DocumentJustificatif.objects.create(
                proprietaire=user,
                type_document=TypeDocument.PERMIS_CONDUIRE,
                fichier=request.FILES["permis_verso"],
                statut=StatutDocument.EN_ATTENTE,
            )

        return Response(SerializerProfilLivreur(profil, context={"request": request}).data)

    def put(self, request):
        return self.patch(request)
