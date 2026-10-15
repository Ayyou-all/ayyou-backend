from django.apps import AppConfig


class ConfigurationCatalogue(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "applications.catalogue"
    label = "catalogue"
    verbose_name = "Catalogue et menus"

