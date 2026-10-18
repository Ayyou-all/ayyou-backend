from django.contrib import admin

from .models import PaiementAbonnement, TentativePaiement


@admin.register(TentativePaiement)
class AdminTentativePaiement(admin.ModelAdmin):
    list_display = [
        "reference_paiement",
        "commande",
        "montant_fcfa",
        "statut",
        "environnement",
        "date_creation",
        "date_confirmation",
    ]
    list_filter = ["statut", "environnement", "date_creation"]
    search_fields = ["reference_paiement", "token_paytech", "commande__reference"]
    readonly_fields = ["donnees_ipn", "date_creation", "date_confirmation"]


@admin.register(PaiementAbonnement)
class AdminPaiementAbonnement(admin.ModelAdmin):
    list_display = ["reference_paiement", "etablissement", "montant_fcfa", "statut", "methode_paiement", "date_confirmation", "date_fin_periode"]
    list_filter = ["statut", "environnement", "date_creation"]
    search_fields = ["reference_paiement", "token_paytech", "etablissement__nom"]
    readonly_fields = ["donnees_ipn", "date_creation", "date_confirmation"]
