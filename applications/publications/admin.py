"""
Configuration Django Admin pour les publications vidéo et photo AYYOU.
"""

from django.contrib import admin

from .models import MentionJeaime, Publication


@admin.register(Publication)
class AdminPublication(admin.ModelAdmin):
    list_display = [
        "titre",
        "etablissement",
        "type_media",
        "duree_secondes",
        "plat",
        "nombre_vues",
        "nombre_partages",
        "est_publie",
        "date_publication",
    ]
    list_filter = ["type_media", "est_publie", "date_publication"]
    search_fields = ["titre", "description", "etablissement__nom"]
    readonly_fields = ["nombre_vues", "nombre_partages"]


@admin.register(MentionJeaime)
class AdminMentionJeaime(admin.ModelAdmin):
    list_display = ["utilisateur", "publication", "date_creation"]
    search_fields = ["utilisateur__email", "utilisateur__nom_complet", "publication__titre"]
