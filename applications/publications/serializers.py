"""
Serializers du domaine Publications pour AYYOU (conforme à l'accueil vidéo et à Ayyou Studio).
"""

from rest_framework import serializers

from applications.catalogue.models import Plat
from applications.catalogue.serializers import SerializerPlat
from applications.communs.fichiers import valider_image
from applications.communs.outils import construire_url_absolue

from .analyseur_video import valider_fichier_video
from .models import MentionJeaime, Publication, TypeMedia


class SerializerPublicationFil(serializers.ModelSerializer):
    """
    Format exact de la carte vidéo / photo du fil d'accueil AYYOU (interface PublicationFil).
    """

    identifiant = serializers.IntegerField(source="id", read_only=True)
    identifiantRestaurant = serializers.IntegerField(source="etablissement.id", read_only=True)
    nomRestaurant = serializers.CharField(source="etablissement.nom", read_only=True)
    nomUtilisateurRestaurant = serializers.SerializerMethodField()
    adresseLogoRestaurant = serializers.SerializerMethodField()
    estAbonne = serializers.SerializerMethodField()
    plat = serializers.SerializerMethodField()
    descriptionAccroche = serializers.CharField(source="description", read_only=True)
    adresseMedia = serializers.SerializerMethodField()
    adresseVideo = serializers.SerializerMethodField()
    typeMedia = serializers.CharField(source="type_media", read_only=True)
    nombreJeaime = serializers.SerializerMethodField()
    estAime = serializers.SerializerMethodField()
    nombrePartages = serializers.IntegerField(source="nombre_partages", read_only=True)
    nombreVues = serializers.IntegerField(source="nombre_vues", read_only=True)

    class Meta:
        model = Publication
        fields = [
            "identifiant",
            "identifiantRestaurant",
            "nomRestaurant",
            "nomUtilisateurRestaurant",
            "adresseLogoRestaurant",
            "estAbonne",
            "plat",
            "descriptionAccroche",
            "adresseMedia",
            "adresseVideo",
            "typeMedia",
            "nombreJeaime",
            "estAime",
            "nombrePartages",
            "nombreVues",
        ]

    def get_nomUtilisateurRestaurant(self, obj):
        return f"@{obj.etablissement.nom_utilisateur}"

    def get_adresseLogoRestaurant(self, obj):
        return construire_url_absolue(self.context.get("request"), obj.etablissement.logo) or ""

    def get_estAbonne(self, obj):
        req = self.context.get("request")
        user = getattr(req, "user", None)
        if not user or not user.is_authenticated:
            return False
        # Vérification si l'utilisateur suit l'établissement
        return hasattr(user, "abonnements_etablissements") and user.abonnements_etablissements.filter(
            etablissement=obj.etablissement
        ).exists()

    def get_plat(self, obj):
        if not obj.plat:
            return None
        return SerializerPlat(obj.plat, context=self.context).data

    def get_adresseMedia(self, obj):
        req = self.context.get("request")
        if obj.image_miniature:
            return construire_url_absolue(req, obj.image_miniature) or ""
        if obj.type_media == TypeMedia.IMAGE and obj.fichier_media:
            return construire_url_absolue(req, obj.fichier_media) or ""
        return ""

    def get_adresseVideo(self, obj):
        req = self.context.get("request")
        if obj.type_media == TypeMedia.VIDEO and obj.fichier_media:
            return construire_url_absolue(req, obj.fichier_media) or ""
        return None

    def get_nombreJeaime(self, obj):
        count = obj.mentions_jeaime.count()
        if count >= 1000:
            return f"{count / 1000:.1f}k"
        return str(count)

    def get_estAime(self, obj):
        req = self.context.get("request")
        user = getattr(req, "user", None)
        if not user or not user.is_authenticated:
            return False
        return MentionJeaime.objects.filter(utilisateur=user, publication=obj).exists()


class SerializerCreationPublication(serializers.ModelSerializer):
    """
    Création par le gérant du restaurant dans son studio Ayyou.
    Valide les contraintes strictes vidéo (<= 300s).
    """

    plat_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = Publication
        fields = [
            "id",
            "titre",
            "description",
            "type_media",
            "fichier_media",
            "image_miniature",
            "plat_id",
        ]

    def validate(self, attrs):
        type_media = attrs.get("type_media", TypeMedia.VIDEO)
        fichier = attrs.get("fichier_media")

        if type_media == TypeMedia.VIDEO and fichier:
            # Analyse des métadonnées vidéo et blocage si > 300 secondes
            duree = valider_fichier_video(fichier)
            if duree is not None:
                attrs["duree_secondes"] = int(duree)
        if type_media == TypeMedia.IMAGE and fichier:
            valider_image(fichier)  # une « photo » ne peut pas être un fichier HTML ou SVG
        if attrs.get("image_miniature"):
            valider_image(attrs["image_miniature"])

        plat_id = attrs.get("plat_id")
        if plat_id:
            # Vérifier que le plat existe et appartient à l'établissement du gérant
            request = self.context.get("request")
            gerant = request.user if request else None
            plat = Plat.objects.filter(pk=plat_id).first()
            if not plat:
                raise serializers.ValidationError({"plat_id": "Plat associé introuvable."})
            if gerant and hasattr(gerant, "etablissement") and plat.etablissement_id != gerant.etablissement.id:
                raise serializers.ValidationError(
                    {"plat_id": "Vous ne pouvez associer que des plats de votre propre établissement."}
                )

        return attrs


class SerializerStudioVideoItem(serializers.ModelSerializer):
    """Format de liste pour l'interface « Ayyou Studio » du gérant."""

    titrePlat = serializers.CharField(source="titre")
    detailsPlat = serializers.CharField(source="description")
    imageAffiche = serializers.SerializerMethodField()
    videoUrl = serializers.SerializerMethodField()
    typeMedia = serializers.CharField(source="type_media", read_only=True)  # VIDEO ou IMAGE
    nombreJeaime = serializers.SerializerMethodField()
    nombreVues = serializers.CharField(source="nombre_vues")
    datePublication = serializers.SerializerMethodField()

    class Meta:
        model = Publication
        fields = [
            "id",
            "titrePlat",
            "detailsPlat",
            "imageAffiche",
            "videoUrl",
            "typeMedia",
            "nombreJeaime",
            "nombreVues",
            "datePublication",
        ]

    def get_imageAffiche(self, obj):
        req = self.context.get("request")
        return construire_url_absolue(req, obj.image_miniature) or ""

    def get_videoUrl(self, obj):
        req = self.context.get("request")
        return construire_url_absolue(req, obj.fichier_media) or ""

    def get_nombreJeaime(self, obj):
        return str(obj.mentions_jeaime.count())

    def get_datePublication(self, obj):
        return obj.date_publication.strftime("%d/%m/%Y")
