from django.contrib import admin

from .models import CategoriePlat, Plat


@admin.register(CategoriePlat)
class AdminCategoriePlat(admin.ModelAdmin):
    list_display = ["nom", "slug", "ordre"]
    prepopulated_fields = {"slug": ("nom",)}


@admin.register(Plat)
class AdminPlat(admin.ModelAdmin):
    list_display = ["nom", "etablissement", "prix_fcfa", "est_disponible", "est_archive"]
    list_filter = ["est_disponible", "est_archive", "section_menu", "categorie"]
    search_fields = ["nom", "etablissement__nom"]
