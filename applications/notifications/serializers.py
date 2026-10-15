"""
Serializers du domaine Notifications AYYOU (compatibles avec le composant de cloche du gérant).
"""

from rest_framework import serializers

from .models import Notification


class SerializerNotification(serializers.ModelSerializer):
    """
    Format conforme à l'interface NotificationGerant du frontend Angular :
    { id, titre, message, texteVocal, heure, lue, type, numeroCommande }
    """

    texteVocal = serializers.CharField(source="texte_vocal", read_only=True)
    heure = serializers.SerializerMethodField()
    lue = serializers.BooleanField(source="est_lue", read_only=True)
    type = serializers.CharField(source="type_notification", read_only=True)
    numeroCommande = serializers.CharField(source="reference_commande", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "titre",
            "message",
            "texteVocal",
            "heure",
            "lue",
            "type",
            "numeroCommande",
        ]

    def get_heure(self, obj) -> str:
        return obj.date_creation.strftime("%H:%M")
