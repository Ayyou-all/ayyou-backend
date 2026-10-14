"""
Vues HTTP pour les paiements PayTech Sénégal.

Endpoints :
- POST /api/paiements/initier/ : Démarre le paiement et renvoie l'URL de checkout PayTech (Client)
- POST /api/paiements/webhook-ipn/ : Webhook appelé par PayTech (Public, protégé par signature cryptographique)
- GET  /api/paiements/<ref>/statut/ : Vérifie le statut d'un paiement (Client)
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
from applications.utilisateurs.permissions import EstClient

from .models import TentativePaiement
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

        commande = get_object_or_404(Commande, pk=commande_id)
        if commande.client_id != request.user.id and not request.user.is_superuser:
            raise AccesRefuse("Vous ne pouvez vérifier que vos propres commandes.")

        tentative = verifier_statut_paytech_en_ligne(commande_id=int(commande_id))
        return Response(SerializerReponsePaiement(tentative).data, status=status.HTTP_200_OK)
