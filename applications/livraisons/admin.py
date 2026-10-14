from django.contrib import admin

from .models import Livraison, ProfilLivreur


@admin.register(ProfilLivreur)
class AdminProfilLivreur(admin.ModelAdmin):
    list_display = [
        "utilisateur",
        "type_vehicule",
        "nom_vehicule",
        "statut_validation",
        "disponibilite",
        "zone_principale",
    ]
    list_filter = ["type_vehicule", "statut_validation", "disponibilite"]
    search_fields = ["utilisateur__courriel", "utilisateur__nom", "immatriculation"]


@admin.register(Livraison)
class AdminLivraison(admin.ModelAdmin):
    list_display = [
        "commande",
        "livreur",
        "etape",
        "gain_livreur_fcfa",
        "essais_code_echoues",
        "date_assignation",
        "date_livraison",
    ]
    list_filter = ["etape", "date_assignation"]
    search_fields = ["commande__reference", "livreur__utilisateur__nom"]
