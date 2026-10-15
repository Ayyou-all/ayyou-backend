from django.apps import AppConfig


class ConfigurationEtablissements(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "applications.etablissements"
    label = "etablissements"
    verbose_name = "Établissements (restaurants)"

