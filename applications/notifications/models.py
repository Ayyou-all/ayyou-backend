"""
Modèles du domaine Notifications pour AYYOU.

Prend en charge :
- Les notifications in-app pour tous les rôles (Client, Gérant, Livreur, Admin)
- Les alertes vocales pour la cuisine du gérant (ex: synthèse vocale Web Speech API)
- Le suivi en temps réel des étapes de commande et de livraison
"""

from django.conf import settings
from django.db import models


class TypeNotification(models.TextChoices):
    COMMANDE_NOUVELLE = "COMMANDE_NOUVELLE", "Nouvelle commande reçue"
    COMMANDE_EN_PREPARATION = "COMMANDE_EN_PREPARATION", "Commande en cours de préparation"
    COMMANDE_PRETE = "COMMANDE_PRETE", "Commande prête pour retrait"
    LIVREUR_ASSIGNE = "LIVREUR_ASSIGNE", "Livreur assigné à la course"
    LIVREUR_ARRIVE = "LIVREUR_ARRIVE", "Livreur arrivé au restaurant ou chez le client"
    COMMANDE_EN_LIVRAISON = "COMMANDE_EN_LIVRAISON", "Commande en cours de livraison"
    COMMANDE_LIVREE = "COMMANDE_LIVREE", "Commande livrée avec succès"
    COMMANDE_ANNULEE = "COMMANDE_ANNULEE", "Commande annulée ou rejetée"
    NOUVELLE_PUBLICATION = "NOUVELLE_PUBLICATION", "Nouvelle vidéo d'un restaurant suivi"
    VALIDATION_COMPTE = "VALIDATION_COMPTE", "Validation ou refus de compte partenaire"
    ABONNEMENT = "ABONNEMENT", "Abonnement restaurant (essai, paiement, échéance)"
    INFO_SYSTEME = "INFO_SYSTEME", "Information générale du système"


class Notification(models.Model):
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    titre = models.CharField(max_length=150)
    message = models.TextField()
    texte_vocal = models.CharField(
        max_length=255,
        blank=True,
        help_text="Texte court et clair énoncé vocalement en cuisine pour le gérant",
    )
    type_notification = models.CharField(
        max_length=40,
        choices=TypeNotification.choices,
        default=TypeNotification.INFO_SYSTEME,
    )
    reference_commande = models.CharField(
        max_length=50,
        blank=True,
        help_text="Référence de commande associée (ex: CMD-20261013-1234)",
    )
    est_lue = models.BooleanField(default=False, db_index=True)
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-date_creation"]
        indexes = [
            models.Index(fields=["destinataire", "est_lue", "-date_creation"]),
        ]

    def __str__(self) -> str:
        return f"[{self.type_notification}] -> {self.destinataire.nom_complet}: {self.titre}"
