from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import DocumentJustificatif, Utilisateur


@admin.register(Utilisateur)
class AdminUtilisateur(UserAdmin):
    ordering = ["-date_creation"]
    list_display = ["courriel", "prenom", "nom", "role", "is_active", "date_creation"]
    list_filter = ["role", "is_active"]
    search_fields = ["courriel", "telephone", "prenom", "nom"]
    fieldsets = (
        (None, {"fields": ("courriel", "password")}),
        ("Identité", {"fields": ("prenom", "nom", "telephone", "adresse", "photo", "preferences_alimentaires")}),
        ("Rôle et accès", {"fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_creation")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("courriel", "prenom", "nom", "telephone", "role", "password1", "password2")}),
    )


@admin.register(DocumentJustificatif)
class AdminDocumentJustificatif(admin.ModelAdmin):
    list_display = ["proprietaire", "type_document", "statut", "date_envoi"]
    list_filter = ["type_document", "statut"]
