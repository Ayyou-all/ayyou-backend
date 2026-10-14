"""Serializers des établissements (vue publique et vue gérant)."""

from django.conf import settings
from rest_framework import serializers

from applications.communs.outils import construire_url_absolue

from .models import Etablissement


class SerializerEtablissementPublic(serializers.ModelSerializer):
    """Fiche publique (interface Angular `Restaurant`)."""

    adresse_logo = serializers.SerializerMethodField()
    adresse_couverture = serializers.SerializerMethodField()
    nombre_abonnes = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Etablissement
        fields = [
            "id", "type_etablissement", "nom", "nom_utilisateur", "description", "specialite", "adresse",
            "quartier_ville", "heure_ouverture", "heure_fermeture", "est_ouvert", "adresse_logo",
            "adresse_couverture", "frais_livraison_fcfa", "delai_livraison_texte", "latitude", "longitude",
            "nombre_abonnes",
        ]

    def get_adresse_logo(self, etablissement):
        return construire_url_absolue(self.context.get("request"), etablissement.logo)

    def get_adresse_couverture(self, etablissement):
        return construire_url_absolue(self.context.get("request"), etablissement.couverture)


class SerializerMonEtablissement(SerializerEtablissementPublic):
    """Vue du gérant : ajoute les champs modifiables et le statut de validation (lecture seule)."""

    logo = serializers.FileField(required=False, allow_null=True, write_only=True)
    couverture = serializers.FileField(required=False, allow_null=True, write_only=True)

    class Meta(SerializerEtablissementPublic.Meta):
        fields = SerializerEtablissementPublic.Meta.fields + [
            "telephone", "logo", "couverture", "statut_validation", "motif_decision",
        ]
        read_only_fields = ["id", "type_etablissement", "statut_validation", "motif_decision", "nom_utilisateur"]

    def validate_frais_livraison_fcfa(self, valeur):
        if valeur > 10000:
            raise serializers.ValidationError("Frais de livraison anormalement élevés (max 10 000 FCFA).")
        return valeur

    def _verifier_image(self, image):
        if image and image.size > settings.TAILLE_MAX_PHOTO_OCTETS:
            raise serializers.ValidationError("Image trop volumineuse.")
        return image

    def validate_logo(self, image):
        return self._verifier_image(image)

    def validate_couverture(self, image):
        return self._verifier_image(image)
