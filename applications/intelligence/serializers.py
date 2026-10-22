"""
Serializers pour les requêtes adressées à la passerelle IA.
"""

from rest_framework import serializers


class SerializerRequeteRecommandations(serializers.Serializer):
    budget_max_fcfa = serializers.IntegerField(required=False, min_value=100, allow_null=True)
    limite = serializers.IntegerField(required=False, default=10, min_value=1, max_value=50)


class SerializerRequeteChatbot(serializers.Serializer):
    message = serializers.CharField(required=True, min_length=1, max_length=500)
    budget_fcfa = serializers.IntegerField(required=False, min_value=100, allow_null=True)
    quartier = serializers.CharField(required=False, allow_blank=True, default="")
    historique = serializers.ListField(child=serializers.DictField(), required=False, default=list)


class SerializerRequeteRechercheVocale(serializers.Serializer):
    texte = serializers.CharField(min_length=1, max_length=300)
