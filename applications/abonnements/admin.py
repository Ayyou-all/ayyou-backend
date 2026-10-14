"""
Configuration Django Admin pour les abonnements.
"""

from django.contrib import admin

from .models import AbonnementEtablissement


@admin.register(AbonnementEtablissement)
class AdminAbonnementEtablissement(admin.ModelAdmin):
    list_display = ["utilisateur", "etablissement", "date_creation"]
    list_filter = ["date_creation"]
    search_fields = ["utilisateur__email", "utilisateur__nom_complet", "etablissement__nom"]
