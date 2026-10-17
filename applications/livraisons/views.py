"""
Vues HTTP pour l'espace Livreur AYYOU.

Les vues restent minces : elles lisent la requête, appellent un service
(`services.py`) qui applique les règles métier, puis renvoient la réponse.
Chaque action porte uniquement sur la livraison du livreur connecté.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.commandes.models import Commande
from applications.communs.choix import OperateurMobileMoney
from applications.communs.erreurs import ErreurMetier
from applications.communs.fichiers import valider_document, valider_image
from applications.utilisateurs.permissions import EstLivreur

from .models import TypeVehicule
from .serializers import (
    SerializerChangementDisponibilite,
    SerializerLivraisonEnCours,
    SerializerMiseAJourPosition,
    SerializerPointageArticle,
    SerializerProfilLivreur,
    SerializerPropositionLivraison,
    SerializerValidationPinLivreur,
)
from .services import (
    accepter_mission_livraison,
    annuler_course_par_livreur,
    changer_disponibilite,
    declarer_echec_livraison,
    demarrer_trajet_vers_client,
    exiger_livraison_active,
    lister_courses_disponibles,
    livraison_est_bloquee,
    mettre_a_jour_position_gps,
    obtenir_livraison_active,
    obtenir_profil_livreur,
    pointer_article_au_guichet,
    refuser_course,
    signaler_arrivee_domicile_client,
    valider_livraison_avec_pin,
)


def trouver_commande(identifiant) -> Commande:
    """Retrouve une commande par son id numérique ou sa référence (ex : ORD-7K2P9QXA)."""
    identifiant = str(identifiant).strip().lstrip("#")
    if identifiant.isdigit():
        return get_object_or_404(Commande, pk=int(identifiant))
    return get_object_or_404(Commande, reference=identifiant)


class VuePropositionsCourses(APIView):
    """Courses prêtes à être acceptées. Vide si le livreur n'est pas validé ou pas en ligne."""

    permission_classes = [EstLivreur]

    def get(self, request):
        profil = obtenir_profil_livreur(request.user)
        courses = lister_courses_disponibles(profil)
        # Sans position GPS récente, la liste est vide : l'écran livreur affiche alors « Activez votre GPS ».
        return Response(SerializerPropositionLivraison(courses, many=True).data)


class VueAccepterMission(APIView):
    """Le livreur accepte une course : le serveur verrouille la commande et choisit le gagnant."""

    permission_classes = [EstLivreur]

    def post(self, request, commande_id):
        profil = obtenir_profil_livreur(request.user)
        livraison = accepter_mission_livraison(trouver_commande(commande_id), profil)
        return Response(SerializerLivraisonEnCours(livraison).data, status=status.HTTP_201_CREATED)


class VueRefuserCourse(APIView):
    """POST /api/livraisons/<commande>/refuser/ : la course ne sera plus proposée à ce livreur."""

    permission_classes = [EstLivreur]

    def post(self, request, commande_id):
        refuser_course(obtenir_profil_livreur(request.user), trouver_commande(commande_id))
        return Response({"succes": True})


class VueAnnulerCourse(APIView):
    """POST /api/livraisons/mission-en-cours/annuler/ {"motif": "..."} : avant récupération seulement."""

    permission_classes = [EstLivreur]

    def post(self, request):
        annuler_course_par_livreur(obtenir_profil_livreur(request.user), str(request.data.get("motif", "")))
        return Response({"succes": True, "message": "Course annulée. Elle est proposée à un autre livreur."})


class VueEchecLivraison(APIView):
    """
    POST /api/livraisons/mission-en-cours/echec/ {"motif": "CLIENT_ABSENT"}
    Motifs : CLIENT_ABSENT, CLIENT_INJOIGNABLE, ADRESSE_INCORRECTE, PROBLEME_VEHICULE, PROBLEME_RESTAURANT.
    """

    permission_classes = [EstLivreur]

    def post(self, request):
        declarer_echec_livraison(obtenir_profil_livreur(request.user), str(request.data.get("motif", "")))
        return Response({"succes": True, "message": "Échec enregistré. Le support AYYOU va traiter la commande."})


class VueMissionEnCours(APIView):
    """Détail de la course active du livreur connecté."""

    permission_classes = [EstLivreur]

    def get(self, request):
        profil = obtenir_profil_livreur(request.user)
        livraison = obtenir_livraison_active(profil)
        if livraison is None:
            return Response({"mission_active": False, "message": "Aucune course active pour le moment."})
        return Response({
            "mission_active": True,
            "livraison": SerializerLivraisonEnCours(livraison).data,
            "est_bloquee": livraison_est_bloquee(livraison),
            "remise_confirmee": livraison.date_remise_restaurant is not None,
        })


class VuePointerArticle(APIView):
    """Le livreur coche un article au comptoir lors de la vérification."""

    permission_classes = [EstLivreur]

    def post(self, request):
        serializer = SerializerPointageArticle(data=request.data)
        serializer.is_valid(raise_exception=True)
        livraison = exiger_livraison_active(obtenir_profil_livreur(request.user))
        ligne = pointer_article_au_guichet(
            livraison=livraison,
            ligne_id=serializer.validated_data["ligne_id"],
            est_verifie=serializer.validated_data["est_verifie"],
        )
        return Response({"ligne_id": ligne.id, "est_verifie": ligne.est_verifie_par_livreur})


class VueDepartVersClient(APIView):
    """Le livreur quitte le restaurant avec les articles vérifiés."""

    permission_classes = [EstLivreur]

    def post(self, request):
        livraison = exiger_livraison_active(obtenir_profil_livreur(request.user))
        demarrer_trajet_vers_client(livraison)
        return Response({"etape": livraison.etape, "message": "En route vers le client."})


class VueArriveeClient(APIView):
    """Le livreur signale son arrivée à l'adresse du client."""

    permission_classes = [EstLivreur]

    def post(self, request):
        livraison = exiger_livraison_active(obtenir_profil_livreur(request.user))
        signaler_arrivee_domicile_client(livraison)
        return Response({"etape": livraison.etape, "message": "Arrivé à l'adresse du client."})


class VueCloturerLivraisonPin(APIView):
    """Le livreur saisit le PIN du client pour clôturer SA livraison (jamais celle d'un autre)."""

    permission_classes = [EstLivreur]

    def post(self, request):
        serializer = SerializerValidationPinLivreur(data=request.data)
        serializer.is_valid(raise_exception=True)
        profil = obtenir_profil_livreur(request.user)
        livraison = valider_livraison_avec_pin(profil, serializer.validated_data["code_pin"])
        return Response({
            "succes": True,
            "message": "Livraison clôturée avec succès. Félicitations pour votre course !",
            "gain_fcfa": livraison.gain_livreur_fcfa,
        })


class VuePositionGpsLivreur(APIView):
    """Réception de la position GPS réelle du téléphone du livreur."""

    permission_classes = [EstLivreur]

    def post(self, request):
        return self.patch(request)

    def patch(self, request):
        profil = obtenir_profil_livreur(request.user)
        serializer = SerializerMiseAJourPosition(data=request.data)
        serializer.is_valid(raise_exception=True)
        latitude = float(serializer.validated_data["latitude"])
        longitude = float(serializer.validated_data["longitude"])
        mettre_a_jour_position_gps(profil, latitude, longitude)
        return Response({
            "succes": True,
            "latitude": latitude,
            "longitude": longitude,
            "date_derniere_position": profil.date_derniere_position.isoformat(),
        })


class VueDisponibiliteLivreur(APIView):
    """Interrupteur En ligne / Hors ligne (refusé si le profil n'est pas validé)."""

    permission_classes = [EstLivreur]

    def post(self, request):
        return self.patch(request)

    def patch(self, request):
        serializer = SerializerChangementDisponibilite(data=request.data)
        serializer.is_valid(raise_exception=True)
        profil = changer_disponibilite(obtenir_profil_livreur(request.user), serializer.validated_data["disponibilite"])
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

        # Mise à jour de la photo de profil (fichier contrôlé : vraie image JPG/PNG/WEBP)
        if "photo" in request.FILES:
            user.photo = valider_image(request.FILES["photo"])
            utilisateur_modifie = True

        # Mise à jour du mot de passe
        nouveau_mdp = data.get("nouveau_mot_de_passe") or data.get("nouveauMotDePasse") or data.get("mot_de_passe")
        if nouveau_mdp:
            nouveau_mdp = str(nouveau_mdp).strip()
            if len(nouveau_mdp) < 6:
                raise ErreurMetier("Le mot de passe doit comporter au moins 6 caractères.", code="mot_de_passe_court")

            # L'ancien mot de passe est obligatoire : un jeton volé ne suffit pas à changer le mot de passe.
            ancien_mdp = data.get("ancien_mot_de_passe") or data.get("ancienMotDePasse")
            if not ancien_mdp or not user.check_password(ancien_mdp):
                raise ErreurMetier("L'ancien mot de passe saisi est incorrect.", code="ancien_mot_de_passe_invalide")

            user.set_password(nouveau_mdp)
            utilisateur_modifie = True

        if utilisateur_modifie:
            user.save()

        # 2. Mise à jour des données spécifiques livreur (véhicule, immatriculation, zone)
        profil_modifie = False
        type_vehicule = data.get("type_vehicule") or data.get("typeVehicule")
        if type_vehicule:
            type_vehicule = str(type_vehicule).upper().strip()
            if type_vehicule not in TypeVehicule.values:
                raise ErreurMetier("Type de véhicule inconnu.", code="type_vehicule_invalide")
            profil.type_vehicule = type_vehicule
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

        numero_reversement = data.get("numero_reversement")
        if numero_reversement is not None:
            profil.numero_reversement = str(numero_reversement).replace(" ", "")
            profil_modifie = True

        operateur_reversement = data.get("operateur_reversement")
        if operateur_reversement:
            if operateur_reversement not in OperateurMobileMoney.values:
                raise ErreurMetier("Opérateur Mobile Money inconnu.", code="operateur_invalide")
            profil.operateur_reversement = operateur_reversement
            profil_modifie = True

        if profil_modifie:
            profil.save()

        # 3. Téléversement éventuel de documents justificatifs (Permis recto / verso)
        from applications.utilisateurs.models import DocumentJustificatif, TypeDocument, StatutDocument
        if "permis_recto" in request.FILES:
            DocumentJustificatif.objects.create(
                proprietaire=user,
                type_document=TypeDocument.PERMIS_CONDUIRE,
                fichier=valider_document(request.FILES["permis_recto"]),
                statut=StatutDocument.EN_ATTENTE,
            )
        if "permis_verso" in request.FILES:
            DocumentJustificatif.objects.create(
                proprietaire=user,
                type_document=TypeDocument.PERMIS_CONDUIRE,
                fichier=valider_document(request.FILES["permis_verso"]),
                statut=StatutDocument.EN_ATTENTE,
            )

        return Response(SerializerProfilLivreur(profil, context={"request": request}).data)

    def put(self, request):
        return self.patch(request)
