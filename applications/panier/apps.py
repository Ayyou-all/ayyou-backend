from django.apps import AppConfig


class ConfigurationPanier(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "applications.panier"
    label = "panier"
    verbose_name = "Panier"

