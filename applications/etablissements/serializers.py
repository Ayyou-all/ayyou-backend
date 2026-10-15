"""Serializers des établissements (vue publique et vue gérant)."""

from django.conf import settings
from rest_framework import serializers

from applications.communs.outils import construire_url_absolue

from .models import Etablissement


class SerializerEtablissementPublic(serializers.ModelSerializer):
    """Fiche publique (interface Angular `Restaurant`)."""

    adresse_logo = serializers.SerializerMethodField()
    adresse_couverture = serializers.SerializerMethodField()
    nombre_abonnes = serializers.SerializerMethodField()
    est_abonne = serializers.SerializerMethodField()
    est_aime = serializers.SerializerMethodField()
    nombre_likes = serializers.SerializerMethodField()
    nombre_likes_videos = serializers.SerializerMethodField()
    plats = serializers.SerializerMethodField()

    class Meta:
        model = Etablissement
        fields = [
            "id", "type_etablissement", "nom", "nom_utilisateur", "description", "specialite", "adresse",
            "quartier_ville", "heure_ouverture", "heure_fermeture", "est_ouvert", "adresse_logo",
            "adresse_couverture", "frais_livraison_fcfa", "delai_livraison_texte", "latitude", "longitude",
            "nombre_abonnes", "est_abonne", "est_aime", "nombre_likes", "nombre_likes_videos", "plats",
        ]

    def get_adresse_logo(self, etablissement):
        return construire_url_absolue(self.context.get("request"), etablissement.logo)

    def get_adresse_couverture(self, etablissement):
        return construire_url_absolue(self.context.get("request"), etablissement.couverture)

    def get_nombre_abonnes(self, etablissement):
        return etablissement.abonnements.count() if hasattr(etablissement, "abonnements") else 0

    def get_est_abonne(self, etablissement):
        req = self.context.get("request")
        user = getattr(req, "user", None)
        if not user or not user.is_authenticated:
            return False
        return etablissement.abonnements.filter(utilisateur=user).exists()

    def get_est_aime(self, etablissement):
        req = self.context.get("request")
        user = getattr(req, "user", None)
        if not user or not user.is_authenticated:
            return False
        return hasattr(etablissement, "likes") and etablissement.likes.filter(utilisateur=user).exists()

    def get_nombre_likes(self, etablissement):
        return etablissement.likes.count() if hasattr(etablissement, "likes") else 0

    def get_nombre_likes_videos(self, etablissement):
        from applications.publications.models import MentionJeaime
        return MentionJeaime.objects.filter(publication__etablissement=etablissement).count()

    def get_plats(self, etablissement):
        from applications.catalogue.serializers import SerializerPlat
        plats = etablissement.plats.filter(est_archive=False, est_disponible=True)
        return SerializerPlat(plats, many=True, context=self.context).data


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
