from django.contrib import admin

from .models import TentativePaiement


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
