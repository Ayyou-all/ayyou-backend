"""
Vues HTTP d'administration de la plateforme AYYOU.
Strictement réservées aux utilisateurs ayant le rôle ADMIN.
"""

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.etablissements.models import Etablissement
from applications.livraisons.models import ProfilLivreur
from applications.utilisateurs.permissions import EstAdministrateur

from .serializers import (
    SerializerDecisionPartenaire,
    SerializerEtablissementModeration,
    SerializerLivreurModeration,
)
from .services import (
    appliquer_decision_etablissement,
    appliquer_decision_livreur,
    calculer_statistiques_globales,
)


class VueStatistiquesGlobales(APIView):
    """Tableau de bord : indicateurs globaux de la plateforme."""

    permission_classes = [EstAdministrateur]

    def get(self, request):
        stats = calculer_statistiques_globales()
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


class VueCommandesAdministration(generics.ListAPIView):
    """
    Supervision globale des commandes pour le Superadmin.
    Supporte les filtres par statut ('EN_ATTENTE', 'EN_COURS', 'LIVREES', 'ANNULEES').
    """

    permission_classes = [EstAdministrateur]
    serializer_class = SerializerCommandeAdministration
    pagination_class = None

    def get_queryset(self):
        qs = (
            Commande.objects.all()
            .select_related("client", "etablissement")
            .prefetch_related("lignes", "livraison__livreur__utilisateur")
            .order_by("-date_creation")
        )
        statut_filtre = self.request.query_params.get("statut")
        if statut_filtre and statut_filtre != "TOUS":
            if statut_filtre in ["EN_ATTENTE", "EN_ATTENTE_PAIEMENT", "CREEE_EN_ATTENTE"]:
                qs = qs.filter(statut__in=["EN_ATTENTE_PAIEMENT", "CREEE_EN_ATTENTE"])
            elif statut_filtre in ["EN_COURS", "EN_PREPARATION", "PRETE_POUR_RETRAIT", "EN_LIVRAISON"]:
                qs = qs.filter(statut__in=["EN_PREPARATION", "PRETE_POUR_RETRAIT", "COURSE_ASSIGNEE", "EN_VERIFICATION", "EN_LIVRAISON", "ARRIVE_CLIENT"])
            elif statut_filtre == "LIVREES":
                qs = qs.filter(statut="LIVREE")
            elif statut_filtre == "ANNULEES":
                qs = qs.filter(statut__in=["REFUSEE_ANNULEE", "ECHEC_LIVRAISON"])
        return qs


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
        action = request.data.get("action", "basculer")
        if action == "activer":
            user.is_active = True
        elif action == "desactiver" or action == "bannir":
            user.is_active = False
        else:
            user.is_active = not user.is_active
        user.save(update_fields=["is_active"])

        return Response({
            "succes": True,
            "id": user.id,
            "estActif": user.is_active,
            "statut": "ACTIF" if user.is_active else "INACTIF",
            "message": f"Compte de {user.nom_complet} {'activé' if user.is_active else 'désactivé'} avec succès.",
        })

