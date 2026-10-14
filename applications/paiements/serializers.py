"""
Serializers du domaine Paiement PayTech pour AYYOU.
"""

from rest_framework import serializers

from .models import TentativePaiement


class SerializerDemandePaiement(serializers.Serializer):
    commande_id = serializers.IntegerField()
    url_succes = serializers.URLField(required=False, allow_blank=True, default="")
    url_annulation = serializers.URLField(required=False, allow_blank=True, default="")


class SerializerReponsePaiement(serializers.ModelSerializer):
    class Meta:
        model = TentativePaiement
        fields = [
            "id",
            "reference_paiement",
            "token_paytech",
            "url_redirection",
            "statut",
            "montant_fcfa",
            "environnement",
            "date_creation",
            "date_confirmation",
        ]
