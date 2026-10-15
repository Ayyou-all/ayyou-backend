"""Représentation JSON des utilisateurs et de leurs documents."""

import os
from django.conf import settings
from rest_framework import serializers

from applications.communs.outils import construire_url_absolue

from .models import DocumentJustificatif, TypeDocument, Utilisateur


class SerializerUtilisateur(serializers.ModelSerializer):
    """Profil renvoyé au frontend (correspond à l'interface Angular `Utilisateur`)."""

    adresse_photo = serializers.SerializerMethodField()
    nom_etablissement = serializers.SerializerMethodField()
    type_vehicule = serializers.SerializerMethodField()
    nom_vehicule = serializers.SerializerMethodField()
    immatriculation = serializers.SerializerMethodField()
    zone_principale = serializers.SerializerMethodField()
    est_actif = serializers.BooleanField(source="is_active", read_only=True)

    class Meta:
        model = Utilisateur
        fields = [
            "id", "prenom", "nom", "courriel", "telephone", "role", "adresse", "adresse_photo",
            "preferences_alimentaires", "nom_etablissement", "type_vehicule", "nom_vehicule",
            "immatriculation", "zone_principale", "est_actif", "date_creation",
        ]
        read_only_fields = ["id", "courriel", "role", "est_actif", "date_creation"]

    def get_adresse_photo(self, utilisateur):
        return construire_url_absolue(self.context.get("request"), utilisateur.photo)

    def get_nom_etablissement(self, utilisateur):
        etablissement = getattr(utilisateur, "etablissement", None)
        return etablissement.nom if etablissement else None

    def get_type_vehicule(self, utilisateur):
        profil = getattr(utilisateur, "profil_livreur", None)
        return profil.type_vehicule if profil else None

    def get_nom_vehicule(self, utilisateur):
        profil = getattr(utilisateur, "profil_livreur", None)
        return profil.nom_vehicule if profil else None

    def get_immatriculation(self, utilisateur):
        profil = getattr(utilisateur, "profil_livreur", None)
        return profil.immatriculation if profil else None

    def get_zone_principale(self, utilisateur):
        profil = getattr(utilisateur, "profil_livreur", None)
        return profil.zone_principale if profil else None


class SerializerModificationProfil(serializers.ModelSerializer):
    """Champs qu'un utilisateur peut modifier lui-même (jamais son rôle)."""

    photo = serializers.FileField(required=False, allow_null=True)
    courriel = serializers.EmailField(required=False)

    class Meta:
        model = Utilisateur
        fields = ["prenom", "nom", "telephone", "adresse", "courriel", "photo", "preferences_alimentaires"]

    def validate_photo(self, photo):
        if photo and photo.size > settings.TAILLE_MAX_PHOTO_OCTETS:
            raise serializers.ValidationError("La photo dépasse la taille maximale autorisée.")
        return photo


class SerializerDocumentJustificatif(serializers.ModelSerializer):
    url_fichier = serializers.SerializerMethodField()
    nom_fichier = serializers.SerializerMethodField()
    taille_fichier = serializers.SerializerMethodField()
    extension = serializers.SerializerMethodField()
    est_image = serializers.SerializerMethodField()
    est_pdf = serializers.SerializerMethodField()
    type_document_libelle = serializers.CharField(source="get_type_document_display", read_only=True)

    class Meta:
        model = DocumentJustificatif
        fields = [
            "id",
            "type_document",
            "type_document_libelle",
            "fichier",
            "url_fichier",
            "nom_fichier",
            "taille_fichier",
            "extension",
            "est_image",
            "est_pdf",
            "statut",
            "motif_rejet",
            "date_envoi",
            "date_verification",
        ]
        read_only_fields = ["id", "statut", "motif_rejet", "date_envoi", "date_verification"]

    EXTENSIONS_AUTORISEES = (".pdf", ".jpg", ".jpeg", ".png")

    def get_url_fichier(self, obj):
        return construire_url_absolue(self.context.get("request"), obj.fichier)

    def get_nom_fichier(self, obj):
        if obj.fichier and obj.fichier.name:
            return os.path.basename(obj.fichier.name)
        return ""

    def get_taille_fichier(self, obj):
        if obj.fichier:
            try:
                octets = obj.fichier.size
                if octets < 1024:
                    return f"{octets} o"
                elif octets < 1024 * 1024:
                    return f"{octets / 1024:.1f} Ko"
                else:
                    return f"{octets / (1024 * 1024):.1f} Mo"
            except Exception:
                pass
        return "Taille inconnue"

    def get_extension(self, obj):
        if obj.fichier and obj.fichier.name:
            _, ext = os.path.splitext(obj.fichier.name)
            return ext.lstrip(".").lower()
        return ""

    def get_est_image(self, obj):
        return self.get_extension(obj) in ["png", "jpg", "jpeg", "webp", "gif", "svg"]

    def get_est_pdf(self, obj):
        return self.get_extension(obj) == "pdf"

    def validate_fichier(self, fichier):
        if not fichier.name.lower().endswith(self.EXTENSIONS_AUTORISEES):
            raise serializers.ValidationError("Formats acceptés : PDF, JPG, PNG.")
        if fichier.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("Le document ne doit pas dépasser 10 Mo.")
        return fichier

    def validate_type_document(self, type_document):
        if type_document not in TypeDocument.values:
            raise serializers.ValidationError("Type de document inconnu.")
        return type_document
