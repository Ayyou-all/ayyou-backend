"""Représentation JSON des utilisateurs et de leurs documents."""

import os
from django.conf import settings
from rest_framework import serializers

from django.urls import reverse

from applications.communs.fichiers import valider_document, valider_image
from applications.communs.validation import (
    texte_obligatoire,
    valider_nouveau_mot_de_passe,
    valider_telephone_unique,
)
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

    photo = serializers.FileField(required=False, allow_null=True, validators=[valider_image])
    courriel = serializers.EmailField(required=False)

    class Meta:
        model = Utilisateur
        fields = ["prenom", "nom", "telephone", "adresse", "courriel", "photo", "preferences_alimentaires"]

    def validate_prenom(self, valeur):
        return texte_obligatoire(valeur, "Le prénom est obligatoire.")

    def validate_nom(self, valeur):
        return texte_obligatoire(valeur, "Le nom est obligatoire.")

    def validate_telephone(self, valeur):
        return valider_telephone_unique(valeur, self.instance)

    def validate_courriel(self, valeur):
        courriel = valeur.strip().lower()
        if Utilisateur.objects.filter(courriel__iexact=courriel).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Cette adresse e-mail est déjà utilisée par un autre compte.")
        return courriel


class SerializerChangementMotDePasse(serializers.Serializer):
    """Changement de mot de passe par l'utilisateur connecté (erreurs renvoyées champ par champ)."""

    ancien_mot_de_passe = serializers.CharField(write_only=True)
    nouveau_mot_de_passe = serializers.CharField(write_only=True)
    confirmation_mot_de_passe = serializers.CharField(write_only=True)

    def validate_ancien_mot_de_passe(self, valeur):
        if not self.context["request"].user.check_password(valeur):
            raise serializers.ValidationError("L'ancien mot de passe est incorrect.")
        return valeur

    def validate_nouveau_mot_de_passe(self, valeur):
        return valider_nouveau_mot_de_passe(valeur, self.context["request"].user)

    def validate(self, donnees):
        if donnees["nouveau_mot_de_passe"] != donnees["confirmation_mot_de_passe"]:
            raise serializers.ValidationError({"confirmation_mot_de_passe": "Les mots de passe ne correspondent pas."})
        return donnees


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
        # Le chemin brut du fichier n'est jamais renvoyé : le document se lit via l'API protégée.
        extra_kwargs = {"fichier": {"write_only": True}}

    def get_url_fichier(self, obj):
        """URL de l'API protégée (JWT obligatoire), jamais l'URL publique /medias/."""
        url = reverse("fichier-document", kwargs={"pk": obj.pk})
        requete = self.context.get("request")
        return requete.build_absolute_uri(url) if requete else url

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
        return self.get_extension(obj) in ["png", "jpg", "jpeg"]

    def get_est_pdf(self, obj):
        return self.get_extension(obj) == "pdf"

    def validate_fichier(self, fichier):
        return valider_document(fichier)

    def validate_type_document(self, type_document):
        if type_document not in TypeDocument.values:
            raise serializers.ValidationError("Type de document inconnu.")
        return type_document
