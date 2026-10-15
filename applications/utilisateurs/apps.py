from django.apps import AppConfig


class ConfigurationUtilisateurs(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "applications.utilisateurs"
    label = "utilisateurs"
    verbose_name = "Utilisateurs et rôles"

