"""
Vues HTTP pour les paiements PayTech Sénégal.

Endpoints :
- POST /api/paiements/initier/ : Démarre le paiement et renvoie l'URL de checkout PayTech (Client)
- POST /api/paiements/webhook-ipn/ : Webhook appelé par PayTech (Public, protégé par signature cryptographique)
- GET  /api/paiements/<ref>/statut/ : Vérifie le statut d'un paiement (Client)
- GET  /api/paiements/abonnement/ : état de l'abonnement du restaurant + historique (Gérant)
- POST /api/paiements/abonnement/payer/ : lien PayTech pour payer 1 mois (Gérant)
- POST /api/paiements/abonnement/verifier/ : demande le statut réel à PayTech au retour (Gérant)
"""

from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.commandes.models import Commande
from applications.communs.erreurs import AccesRefuse
from applications.etablissements.services import obtenir_etablissement_du_gerant
from applications.utilisateurs.permissions import EstClient, EstGerantEtablissement

from .abonnement import initier_paiement_abonnement, resume_abonnement, resume_paiement, verifier_paiement_abonnement

from .models import StatutPaiement, TentativePaiement
from .serializers import SerializerDemandePaiement, SerializerReponsePaiement
from .services import (
    initier_demande_paiement_paytech,
    traiter_notification_ipn_paytech,
    verifier_statut_paytech_en_ligne,
)


class VueInitierPaiement(APIView):
    """
    Le client demande à payer sa commande.
    Le backend vérifie et renvoie l'URL de redirection sécurisée PayTech.
    """

    permission_classes = [EstClient]

    def post(self, request):
        serializer = SerializerDemandePaiement(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data

        commande = get_object_or_404(Commande, pk=donnees["commande_id"])

        if commande.client_id != request.user.id and not request.user.is_superuser:
            raise AccesRefuse("Vous ne pouvez payer que vos propres commandes.")

        tentative = initier_demande_paiement_paytech(
            commande=commande,
            url_succes_client=donnees.get("url_succes", ""),
            url_annulation_client=donnees.get("url_annulation", ""),
        )

        return Response(
            SerializerReponsePaiement(tentative).data,
            status=status.HTTP_201_CREATED,
        )


@method_decorator(csrf_exempt, name="dispatch")
class VueWebhookIpnPayTech(APIView):
    """
    Réception des notifications IPN (Instant Payment Notification) envoyées par les serveurs PayTech.
    Validation par HMAC SHA-256 ou hash des clés API.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        donnees_ipn = request.data
        tentative = traiter_notification_ipn_paytech(donnees_ipn)
        return Response(
            {
                "succes": 1,
                "statut": tentative.statut,
                "message": "Notification IPN traitée avec succès.",
            },
            status=status.HTTP_200_OK,
        )


class VueStatutPaiement(APIView):
    """Vérification du statut d'une tentative de paiement par sa référence."""

    def get(self, request, reference):
        tentative = get_object_or_404(TentativePaiement, reference_paiement=reference)

        if tentative.commande.client_id != request.user.id and not request.user.is_superuser:
            raise AccesRefuse("Accès non autorisé à cette transaction.")

        return Response(SerializerReponsePaiement(tentative).data)


class VueVerifierPaiement(APIView):
    """
    Vérifie l'état d'un paiement auprès de PayTech (par exemple suite à la redirection retour du client)
    et synchronise le statut de la commande en temps réel.
    """

    permission_classes = [EstClient]

    def post(self, request):
        commande_id = request.data.get("commande_id")
        if not commande_id:
            return Response({"detail": "Le paramètre commande_id est requis."}, status=status.HTTP_400_BAD_REQUEST)

        cmd_str = str(commande_id).strip()
        commande = None
        if cmd_str.isdigit():
            commande = Commande.objects.filter(pk=int(cmd_str)).first()
        if not commande:
            commande = Commande.objects.filter(reference=cmd_str).first()
        if not commande:
            return Response({"detail": "Commande introuvable."}, status=status.HTTP_404_NOT_FOUND)

        if commande.client_id != request.user.id and not request.user.is_superuser:
            raise AccesRefuse("Vous ne pouvez vérifier que vos propres commandes.")

        tentative = verifier_statut_paytech_en_ligne(commande_id=commande.id)
        return Response(SerializerReponsePaiement(tentative).data, status=status.HTTP_200_OK)



# ---------------------------------------------------------------------------
# Abonnement mensuel du restaurant (gérant). Volontairement SANS AbonnementValide :
# un restaurant suspendu doit pouvoir consulter son état et payer pour se réactiver.
# ---------------------------------------------------------------------------
def _etat_abonnement(etablissement) -> dict:
    """État de l'abonnement + historique des paiements (les demandes abandonnées sont masquées)."""
    paiements = (
        etablissement.paiements_abonnement.exclude(statut=StatutPaiement.ANNULE)
        .select_related("etablissement")[:24]
    )
    return {
        "abonnement": resume_abonnement(etablissement),
        "historique": [resume_paiement(paiement) for paiement in paiements],
    }


class VueMonAbonnement(APIView):
    permission_classes = [EstGerantEtablissement]

    def get(self, request):
        return Response(_etat_abonnement(obtenir_etablissement_du_gerant(request.user)))


class VuePayerAbonnement(APIView):
    """Renvoie le lien PayTech. L'abonnement ne sera activé qu'à la confirmation de PayTech."""

    permission_classes = [EstGerantEtablissement]

    def post(self, request):
        paiement = initier_paiement_abonnement(obtenir_etablissement_du_gerant(request.user))
        return Response(
            {"reference": paiement.reference_paiement, "url_redirection": paiement.url_redirection},
            status=status.HTTP_201_CREATED,
        )


class VueVerifierAbonnement(APIView):
    """Retour de la page PayTech : on demande le statut réel à PayTech, puis on renvoie l'état à jour."""

    permission_classes = [EstGerantEtablissement]

    def post(self, request):
        etablissement = obtenir_etablissement_du_gerant(request.user)
        verifier_paiement_abonnement(etablissement)
        etablissement.refresh_from_db()
        return Response(_etat_abonnement(etablissement))
