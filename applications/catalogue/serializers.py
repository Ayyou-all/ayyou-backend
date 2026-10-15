"""Serializers du catalogue."""

from django.conf import settings
from rest_framework import serializers

from applications.communs.outils import construire_url_absolue

from .models import CategoriePlat, Plat


class SerializerCategoriePlat(serializers.ModelSerializer):
    class Meta:
        model = CategoriePlat
        fields = ["id", "nom", "slug", "icone", "couleur_fond", "couleur_texte"]


class SerializerPlat(serializers.ModelSerializer):
    """Représentation publique (interface Angular `Plat`)."""

    identifiant_etablissement = serializers.IntegerField(source="etablissement_id", read_only=True)
    nom_etablissement = serializers.CharField(source="etablissement.nom", read_only=True)
    categorie = serializers.CharField(source="categorie.nom", read_only=True, default=None)
    adresse_image = serializers.SerializerMethodField()
    statut = serializers.SerializerMethodField()
    nombre_commandes = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Plat
        fields = [
            "id", "identifiant_etablissement", "nom_etablissement", "nom", "description", "prix_fcfa",
            "adresse_image", "categorie", "section_menu", "statut", "temps_preparation_minutes", "portions",
            "nombre_commandes",
        ]

    def get_adresse_image(self, plat):
        return construire_url_absolue(self.context.get("request"), plat.image)

    def get_statut(self, plat):
        return "DISPONIBLE" if plat.est_commandable else "INDISPONIBLE"


class SerializerGestionPlat(serializers.ModelSerializer):
    """Création / modification d'un plat par le gérant de l'établissement."""

    adresse_image = serializers.SerializerMethodField()
    categorie_id = serializers.PrimaryKeyRelatedField(
        source="categorie", queryset=CategoriePlat.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Plat
        fields = [
            "id", "nom", "description", "prix_fcfa", "image", "adresse_image", "categorie_id", "section_menu",
            "est_disponible", "temps_preparation_minutes", "portions", "date_modification",
        ]
        read_only_fields = ["id", "date_modification"]
        extra_kwargs = {"image": {"write_only": True, "required": False}}

    def get_adresse_image(self, plat):
        return construire_url_absolue(self.context.get("request"), plat.image)

    def validate_prix_fcfa(self, prix):
        if prix < 50 or prix > 500_000:
            raise serializers.ValidationError("Le prix doit être compris entre 50 et 500 000 FCFA.")
        return prix

    def validate_image(self, image):
        if image and image.size > settings.TAILLE_MAX_PHOTO_OCTETS:
            raise serializers.ValidationError("Image trop volumineuse.")
        return image


class SerializerDisponibilite(serializers.Serializer):
    est_disponible = serializers.BooleanField()
