from django.contrib import admin

from .models import Etablissement


@admin.register(Etablissement)
class AdminEtablissement(admin.ModelAdmin):
    list_display = ["nom", "type_etablissement", "quartier_ville", "statut_validation", "est_ouvert"]
    list_filter = ["type_etablissement", "statut_validation", "est_ouvert"]
    search_fields = ["nom", "nom_utilisateur", "gerant__courriel"]
