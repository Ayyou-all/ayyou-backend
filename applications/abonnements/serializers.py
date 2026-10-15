"""
Serializers pour le domaine Abonnements AYYOU.
"""

from rest_framework import serializers

from applications.etablissements.serializers import SerializerEtablissementPublic

from .models import AbonnementEtablissement


class SerializerAbonnement(serializers.ModelSerializer):
    """Présente un abonnement avec les informations détaillées de l'établissement suivi."""

    etablissement = SerializerEtablissementPublic(read_only=True)

    class Meta:
        model = AbonnementEtablissement
        fields = ["id", "etablissement", "date_creation"]
