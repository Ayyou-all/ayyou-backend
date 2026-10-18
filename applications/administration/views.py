"""
Vues HTTP d'administration de la plateforme AYYOU.
Strictement réservées aux utilisateurs ayant le rôle ADMIN.
"""

from datetime import timedelta

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.communs.erreurs import ErreurMetier
from applications.etablissements.models import Etablissement, StatutAbonnement
from applications.livraisons.models import ProfilLivreur
from applications.notifications.models import Notification, TypeNotification
from applications.paiements.abonnement import filtre_statut_abonnement, resume_paiement, statistiques_abonnements
from applications.paiements.models import PaiementAbonnement, StatutPaiement
from applications.utilisateurs.permissions import EstAdministrateur

from .serializers import (
    SerializerDecisionPartenaire,
    SerializerEtablissementModeration,
    SerializerLivreurModeration,
)
from .services import (
    admin_annuler_commande,
    admin_assigner_livreur,
    admin_debloquer_livraison,
    admin_rembourser_commande,
    admin_retirer_livreur,
    appliquer_decision_etablissement,
    appliquer_decision_livreur,
    calculer_statistiques_globales,
)


class VueStatistiquesGlobales(APIView):
    """Tableau de bord : indicateurs globaux de la plateforme."""

    permission_classes = [EstAdministrateur]

    def get(self, request):
        stats = calculer_statistiques_globales(request=request)
        return Response(stats)


class VueEtablissementsModeration(generics.ListAPIView):
    """Liste de tous les établissements partenaires avec filtres optionnels par statut."""

    permission_classes = [EstAdministrateur]
    serializer_class = SerializerEtablissementModeration
    pagination_class = None

    def get_queryset(self):
        qs = Etablissement.objects.all().select_related("gerant").prefetch_related("gerant__documents").order_by("-date_creation")
        statut = self.request.query_params.get("statut")
        if statut:
            qs = qs.filter(statut_validation=statut)
        return qs


class VueLivreursModeration(generics.ListAPIView):
    """Liste des profils livreurs avec filtres optionnels par statut."""

    permission_classes = [EstAdministrateur]
    serializer_class = SerializerLivreurModeration
    pagination_class = None

    def get_queryset(self):
        qs = (
            ProfilLivreur.objects.all()
            .select_related("utilisateur")
            .prefetch_related("utilisateur__documents")
        )
        statut = self.request.query_params.get("statut")
        if statut:
            qs = qs.filter(statut_validation=statut)
        return qs


class VueDecisionEtablissement(APIView):
    """Validation, suspension ou demande de correction d'un restaurant."""

    permission_classes = [EstAdministrateur]

    def post(self, request, pk):
        etablissement = get_object_or_404(Etablissement, pk=pk)
        serializer = SerializerDecisionPartenaire(data=request.data)
        serializer.is_valid(raise_exception=True)

        nouveau_statut = serializer.validated_data["nouveau_statut"]
        motif = serializer.validated_data.get("motif_decision", "")

        maj = appliquer_decision_etablissement(
            etablissement=etablissement,
            nouveau_statut=nouveau_statut,
            motif_decision=motif,
            admin_user=request.user,
        )

        return Response(
            {
                "succes": True,
                "id": maj.id,
                "statutValidation": maj.statut_validation,
                "message": f"Statut de l'établissement mis à jour vers {maj.statut_validation}.",
            }
        )


class VueDecisionLivreur(APIView):
    """Validation, suspension ou refus d'un profil coursier."""

    permission_classes = [EstAdministrateur]

    def post(self, request, pk):
        livreur = get_object_or_404(ProfilLivreur, pk=pk)
        serializer = SerializerDecisionPartenaire(data=request.data)
        serializer.is_valid(raise_exception=True)

        nouveau_statut = serializer.validated_data["nouveau_statut"]
        motif = serializer.validated_data.get("motif_decision", "")

        maj = appliquer_decision_livreur(
            profil_livreur=livreur,
            nouveau_statut=nouveau_statut,
            motif_decision=motif,
            admin_user=request.user,
        )

        return Response(
            {
                "succes": True,
                "id": maj.id,
                "statutValidation": maj.statut_validation,
                "message": f"Statut du profil coursier mis à jour vers {maj.statut_validation}.",
            }
        )


from applications.commandes.models import Commande
from applications.utilisateurs.models import Utilisateur
from .serializers import SerializerCommandeAdministration, SerializerUtilisateurAdministration


class PaginationAdministration(PageNumberPagination):
    page_size = 20
    page_size_query_param = "taille"
    max_page_size = 100


# Regroupements de statuts utilisés par les onglets de l'écran admin
GROUPES_STATUTS = {
    "EN_ATTENTE": ["EN_ATTENTE_PAIEMENT", "CREEE_EN_ATTENTE"],
    "EN_COURS": ["EN_PREPARATION", "PRETE_POUR_RETRAIT", "COURSE_ASSIGNEE", "EN_VERIFICATION", "EN_LIVRAISON", "ARRIVE_CLIENT"],
    "LIVREES": ["LIVREE"],
    "ANNULEES": ["REFUSEE_ANNULEE", "ECHEC_LIVRAISON"],
    "SANS_LIVREUR": ["PRETE_POUR_RETRAIT"],
    "ECHECS": ["ECHEC_LIVRAISON"],
}


class VueCommandesAdministration(generics.ListAPIView):
    """
    GET /api/administration/commandes/?statut=EN_COURS&recherche=ORD-12&date=2026-10-17&page=2
    Liste paginée (20 par page). Filtres appliqués par le serveur, sur toutes les commandes.
    statut : TOUS, EN_ATTENTE, EN_COURS, LIVREES, ANNULEES, SANS_LIVREUR, ECHECS, A_REMBOURSER.
    """

    permission_classes = [EstAdministrateur]
    serializer_class = SerializerCommandeAdministration
    pagination_class = PaginationAdministration

    def get_queryset(self):
        from django.db.models import Q

        qs = (
            Commande.objects.all()
            .select_related("client", "etablissement", "livraison__livreur__utilisateur")
            .prefetch_related("lignes", "tentatives_paiement", "historique_statuts__auteur")
            .order_by("-date_creation")
        )
        statut = self.request.query_params.get("statut", "TOUS")
        if statut == "A_REMBOURSER":
            qs = qs.filter(statut__in=GROUPES_STATUTS["ANNULEES"], tentatives_paiement__statut="CONFIRME").distinct()
        elif statut in GROUPES_STATUTS:
            qs = qs.filter(statut__in=GROUPES_STATUTS[statut])
            if statut == "SANS_LIVREUR":
                qs = qs.filter(livraison__isnull=True)
        if recherche := self.request.query_params.get("recherche", "").strip():
            qs = qs.filter(
                Q(reference__icontains=recherche.lstrip("#"))
                | Q(client__prenom__icontains=recherche)
                | Q(client__nom__icontains=recherche)
                | Q(telephone_contact__icontains=recherche)
                | Q(etablissement__nom__icontains=recherche)
                | Q(livraison__livreur__utilisateur__nom__icontains=recherche)
            )
        if date := self.request.query_params.get("date"):
            qs = qs.filter(date_creation__date=date)
        return qs


class VueActionCommandeAdministration(APIView):
    """
    POST /api/administration/commandes/<id>/<action>/
    action = annuler {"motif"} | rembourser | assigner-livreur {"livreur_id"} | retirer-livreur {"motif"} | debloquer
    Chaque action est enregistrée dans l'historique de la commande avec l'administrateur auteur.
    """

    permission_classes = [EstAdministrateur]

    def post(self, request, pk, action):
        commande = get_object_or_404(Commande, pk=pk)
        motif = str(request.data.get("motif", ""))
        if action == "annuler":
            admin_annuler_commande(commande, request.user, motif)
        elif action == "rembourser":
            admin_rembourser_commande(commande, request.user)
        elif action == "assigner-livreur":
            livreur_id = request.data.get("livreur_id")
            if not str(livreur_id).isdigit():
                raise ErreurMetier("Choisissez un livreur.", code="livreur_obligatoire")
            admin_assigner_livreur(commande, request.user, int(livreur_id))
        elif action == "retirer-livreur":
            admin_retirer_livreur(commande, request.user, motif)
        elif action == "debloquer":
            from django.db import transaction

            with transaction.atomic():
                admin_debloquer_livraison(commande, request.user)
        else:
            return Response({"message": "Action inconnue."}, status=404)
        commande = (
            Commande.objects.select_related("client", "etablissement", "livraison__livreur__utilisateur")
            .prefetch_related("lignes", "tentatives_paiement", "historique_statuts__auteur")
            .get(pk=pk)
        )
        return Response(SerializerCommandeAdministration(commande, context={"request": request}).data)


class VueUtilisateursAdministration(generics.ListAPIView):
    """
    Supervision de tous les comptes de la plateforme pour le Superadmin.
    Supporte les filtres par rôle ('CLIENTS', 'RESTAURANTS', 'LIVREURS').
    """

    permission_classes = [EstAdministrateur]
    serializer_class = SerializerUtilisateurAdministration
    pagination_class = None

    def get_queryset(self):
        qs = Utilisateur.objects.all().order_by("-date_creation")
        role_filtre = self.request.query_params.get("role")
        if role_filtre:
            if role_filtre == "CLIENTS":
                qs = qs.filter(role="CLIENT")
            elif role_filtre == "RESTAURANTS":
                qs = qs.filter(role="RESTAURANT")
            elif role_filtre == "LIVREURS":
                qs = qs.filter(role="LIVREUR")
        return qs


class VueBasculerStatutUtilisateur(APIView):
    """Permet au Superadmin d'activer, désactiver ou bannir un utilisateur."""

    permission_classes = [EstAdministrateur]

    def post(self, request, pk):
        user = get_object_or_404(Utilisateur, pk=pk)
        if user.pk == request.user.pk:
            raise ErreurMetier("Vous ne pouvez pas désactiver votre propre compte.", code="action_interdite")
        action = request.data.get("action", "basculer")
        if action == "activer":
            user.is_active = True
        elif action == "desactiver" or action == "bannir":
            user.is_active = False
        else:
            user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        if not user.is_active:
            # Un compte désactivé ne doit plus recevoir de course ni de commande.
            from applications.livraisons.models import DisponibiliteLivreur

            ProfilLivreur.objects.filter(utilisateur=user, disponibilite=DisponibiliteLivreur.EN_LIGNE).update(
                disponibilite=DisponibiliteLivreur.HORS_LIGNE
            )
            Etablissement.objects.filter(gerant=user).update(est_ouvert=False)

        return Response({
            "succes": True,
            "id": user.id,
            "estActif": user.is_active,
            "statut": "ACTIF" if user.is_active else "INACTIF",
            "message": f"Compte de {user.nom_complet} {'activé' if user.is_active else 'désactivé'} avec succès.",
        })



# ---------------------------------------------------------------------------
# Abonnements des restaurants (modèle économique). Chiffres calculés sur les paiements CONFIRMÉS.
# ---------------------------------------------------------------------------
class VueStatistiquesAbonnements(APIView):
    """Indicateurs, derniers paiements confirmés et dernières alertes d'abonnement de l'admin connecté."""

    permission_classes = [EstAdministrateur]

    def get(self, request):
        derniers = (
            PaiementAbonnement.objects.filter(statut=StatutPaiement.CONFIRME)
            .select_related("etablissement")
            .order_by("-date_confirmation")[:10]
        )
        alertes = Notification.objects.filter(
            destinataire=request.user, type_notification=TypeNotification.ABONNEMENT
        )[:10]
        return Response({
            "statistiques": statistiques_abonnements(),
            "derniers_paiements": [resume_paiement(paiement) for paiement in derniers],
            "alertes": [
                {"id": alerte.id, "titre": alerte.titre, "message": alerte.message,
                 "date_creation": alerte.date_creation, "est_lue": alerte.est_lue}
                for alerte in alertes
            ],
        })


class VueAbonnementsRestaurants(generics.ListAPIView):
    """
    Liste des restaurants et de leur abonnement.
    Filtres : ?recherche=nom, ?statut=ESSAI|ACTIF|SUSPENDU, ?periode=jour|semaine|mois|annee
    (période = restaurants ayant un paiement confirmé dans la période).
    """

    permission_classes = [EstAdministrateur]
    pagination_class = PaginationAdministration

    def get_queryset(self):
        parametres = self.request.query_params
        restaurants = Etablissement.objects.annotate(
            total_paye=Sum("paiements_abonnement__montant_fcfa", filter=Q(paiements_abonnement__statut=StatutPaiement.CONFIRME))
        ).order_by("nom")
        if recherche := parametres.get("recherche", "").strip():
            restaurants = restaurants.filter(nom__icontains=recherche)
        if (statut := parametres.get("statut")) in StatutAbonnement.values:
            restaurants = restaurants.filter(filtre_statut_abonnement(statut))
        debut_jour = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        debuts = {
            "jour": debut_jour,
            "semaine": debut_jour - timedelta(days=debut_jour.weekday()),
            "mois": debut_jour.replace(day=1),
            "annee": debut_jour.replace(month=1, day=1),
        }
        if debut := debuts.get(parametres.get("periode", "")):
            payes = PaiementAbonnement.objects.filter(statut=StatutPaiement.CONFIRME, date_confirmation__gte=debut)
            restaurants = restaurants.filter(id__in=payes.values("etablissement_id"))
        return restaurants

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        lignes = []
        for restaurant in page:
            paiements = restaurant.paiements_abonnement.exclude(statut=StatutPaiement.ANNULE)
            dernier = paiements.first()
            periode_en_cours = paiements.filter(statut=StatutPaiement.CONFIRME).order_by("-date_fin_periode").first()
            lignes.append({
                "id": restaurant.id,
                "nom": restaurant.nom,
                "statut_abonnement": restaurant.statut_abonnement,
                "date_abonnement": periode_en_cours.date_debut_periode if periode_en_cours else None,
                "date_expiration": restaurant.date_echeance_abonnement,
                "jours_restants": restaurant.jours_restants_abonnement,
                "total_paye_fcfa": restaurant.total_paye or 0,
                "dernier_paiement": {
                    "date": dernier.date_confirmation or dernier.date_creation,
                    "montant_fcfa": dernier.montant_fcfa,
                    "statut": dernier.statut,
                } if dernier else None,
            })
        return self.get_paginated_response(lignes)
