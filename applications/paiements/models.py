"""
Modèles du domaine Paiement pour AYYOU.

Prend en charge l'agrégateur sénégalais PayTech (Wave, Orange Money, carte bancaire).
Règles de sécurité :
1. Aucun secret PayTech n'est exposé au frontend.
2. Une tentative de paiement possède une référence unique (ref_command).
3. Une commande n'est marquée comme payée qu'après confirmation cryptographique de l'IPN PayTech.
4. Les notifications webhook répétées sont traitées de manière strictement idempotente.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.communs.outils import generer_reference


class StatutPaiement(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de paiement"
    CONFIRME = "CONFIRME", "Paiement confirmé"
    ECHOUE = "ECHOUE", "Paiement échoué"
    ANNULE = "ANNULE", "Paiement annulé"
    REMBOURSE = "REMBOURSE", "Paiement remboursé"


def generer_reference_paiement() -> str:
    return generer_reference("PAY")


class TentativePaiement(models.Model):
    commande = models.ForeignKey(
        "commandes.Commande",
        on_delete=models.PROTECT,
        related_name="tentatives_paiement",
    )
    reference_paiement = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=generer_reference_paiement,
        help_text="Référence transmise à PayTech (ref_command)",
    )
    token_paytech = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
        help_text="Token de paiement renvoyé par l'API PayTech",
    )
    url_redirection = models.URLField(
        max_length=500,
        blank=True,
        help_text="URL de redirection vers la page de paiement PayTech",
    )
    statut = models.CharField(
        max_length=20,
        choices=StatutPaiement.choices,
        default=StatutPaiement.EN_ATTENTE,
        db_index=True,
    )
    montant_fcfa = models.PositiveIntegerField()
    environnement = models.CharField(
        max_length=10,
        default="test",
        help_text="test (Sandbox) ou prod",
    )
    donnees_ipn = models.JSONField(
        default=dict,
        blank=True,
        help_text="Données brutes reçues lors du webhook IPN pour audit",
    )
    date_creation = models.DateTimeField(default=timezone.now)
    date_confirmation = models.DateTimeField(null=True, blank=True)
    reference_remboursement = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self) -> str:
        return f"{self.reference_paiement} — {self.montant_fcfa} FCFA ({self.get_statut_display()})"


def generer_reference_abonnement() -> str:
    # Le préfixe « ABO- » permet au webhook PayTech de distinguer un abonnement d'une commande.
    return generer_reference("ABO")


class PaiementAbonnement(models.Model):
    """
    Paiement de l'abonnement mensuel d'un restaurant (15 000 FCFA / mois) via PayTech.
    Seul un paiement CONFIRME (notification PayTech vérifiée) prolonge l'abonnement et compte dans les revenus.
    Aucune donnée bancaire n'est stockée : uniquement ce que PayTech renvoie (référence, méthode).
    """

    etablissement = models.ForeignKey(
        "etablissements.Etablissement",
        on_delete=models.PROTECT,
        related_name="paiements_abonnement",
    )
    reference_paiement = models.CharField(max_length=64, unique=True, db_index=True, default=generer_reference_abonnement)
    token_paytech = models.CharField(max_length=128, blank=True, db_index=True)
    url_redirection = models.URLField(max_length=500, blank=True)
    statut = models.CharField(max_length=20, choices=StatutPaiement.choices, default=StatutPaiement.EN_ATTENTE, db_index=True)
    montant_fcfa = models.PositiveIntegerField()
    methode_paiement = models.CharField(max_length=40, blank=True, help_text="Ex : Wave, Orange Money (fourni par PayTech)")
    environnement = models.CharField(max_length=10, default="test")
    # Période d'abonnement achetée (remplie à la confirmation)
    date_debut_periode = models.DateTimeField(null=True, blank=True)
    date_fin_periode = models.DateTimeField(null=True, blank=True)
    donnees_ipn = models.JSONField(default=dict, blank=True, help_text="Données reçues de PayTech, pour audit")
    date_creation = models.DateTimeField(default=timezone.now, db_index=True)
    date_confirmation = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-date_creation"]

    def __str__(self) -> str:
        return f"{self.reference_paiement} — {self.etablissement} — {self.montant_fcfa} FCFA ({self.get_statut_display()})"
