"""
python manage.py traiter_expirations

Traite immédiatement les commandes dont un délai est dépassé (paiement, acceptation, livreur).
Le middleware le fait déjà automatiquement ; cette commande sert pour un cron ou un test manuel.
"""

from django.core.management.base import BaseCommand

from applications.commandes.expirations import traiter_commandes_expirees


class Command(BaseCommand):
    help = "Annule les commandes expirées et alerte quand aucun livreur n'est trouvé."

    def handle(self, *args, **options):
        resultat = traiter_commandes_expirees()
        self.stdout.write(self.style.SUCCESS(f"Expirations traitées : {resultat}"))
