from django.contrib import admin

from .models import Commande, HistoriqueStatutCommande, LigneCommande


class LigneCommandeInline(admin.TabularInline):
    model = LigneCommande
    extra = 0
    readonly_fields = ["nom_plat", "prix_unitaire_fcfa", "quantite", "total_ligne_fcfa"]


class HistoriqueInline(admin.TabularInline):
    model = HistoriqueStatutCommande
    extra = 0
    readonly_fields = ["ancien_statut", "nouveau_statut", "auteur", "commentaire", "date_transition"]


@admin.register(Commande)
class AdminCommande(admin.ModelAdmin):
    list_display = [
        "reference",
        "client",
        "etablissement",
        "statut",
        "mode_paiement",
        "total_fcfa",
        "code_livraison_pin",
        "date_creation",
    ]
    list_filter = ["statut", "mode_paiement", "date_creation"]
    search_fields = ["reference", "client__courriel", "client__nom", "etablissement__nom"]
    inlines = [LigneCommandeInline, HistoriqueInline]
