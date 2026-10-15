"""
Vues HTTP pour le domaine Notifications AYYOU.
"""

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import SerializerNotification
from .services import (
    compter_notifications_non_lues,
    marquer_notification_comme_lue,
    marquer_toutes_notifications_comme_lues,
)


class VueMesNotifications(generics.ListAPIView):
    """
    Récupère la liste des notifications de l'utilisateur connecté.
    Possibilité de filtrer : ?non_lues=true
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SerializerNotification

    def get_queryset(self):
        qs = Notification.objects.filter(destinataire=self.request.user)
        if self.request.query_params.get("non_lues") == "true":
            qs = qs.filter(est_lue=False)
        return qs


class VueCompterNotificationsNonLues(APIView):
    """Renvoie le nombre de notifications non lues (pour le badge de cloche)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        total = compter_notifications_non_lues(request.user)
        return Response({"nombreNonLues": total})


class VueMarquerNotificationLue(APIView):
    """Marque une notification spécifique comme lue."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notif = marquer_notification_comme_lue(notification_id=pk, utilisateur=request.user)
        if not notif:
            return Response({"erreur": "Notification introuvable."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"succes": True, "id": notif.id, "lue": True})


class VueToutMarquerLu(APIView):
    """Marque toutes les notifications de l'utilisateur connecté comme lues."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        nb = marquer_toutes_notifications_comme_lues(request.user)
        return Response({"succes": True, "nombreMarquees": nb})
