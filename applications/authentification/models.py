"""
Modèles pour le domaine de l'authentification.

Contient la gestion sécurisée des codes de vérification envoyés par e-mail (SMTP).
"""

from datetime import timedelta
from django.db import models
from django.utils import timezone


class TypeActionVerification(models.TextChoices):
    INSCRIPTION = "INSCRIPTION", "Vérification lors de l'inscription"
    REINITIALISATION = "REINITIALISATION", "Réinitialisation de mot de passe"
    CONNEXION_SECURISÉE = "CONNEXION_SECURISEE", "Connexion à double facteur"


class CodeVerificationEmail(models.Model):
    """
    Code numérique éphémère (6 chiffres) envoyé par e-mail via SMTP.
    Utilisé pour valider l'adresse avant la création effective du compte.
    """

    courriel = models.EmailField("adresse e-mail", db_index=True)
    code = models.CharField("code de vérification", max_length=6)
    type_action = models.CharField(
        "type d'action",
        max_length=30,
        choices=TypeActionVerification.choices,
        default=TypeActionVerification.INSCRIPTION,
    )
    date_creation = models.DateTimeField("date de création", auto_now_add=True)
    date_expiration = models.DateTimeField("date d'expiration")
    est_utilise = models.BooleanField("code utilisé", default=False)
    tentatives_echouees = models.PositiveIntegerField("tentatives échouées", default=0)
    # Renseignée seulement quand l'utilisateur a saisi le BON code (et non quand un code est remplacé).
    date_verification = models.DateTimeField("date de vérification réussie", null=True, blank=True)

    class Meta:
        verbose_name = "code de vérification e-mail"
        verbose_name_plural = "codes de vérification e-mail"
        ordering = ["-date_creation"]
        indexes = [
            models.Index(fields=["courriel", "type_action", "est_utilise"]),
        ]

    def __str__(self) -> str:
        statut = "Utilisé" if self.est_utilise else ("Expiré" if self.est_expire else "Actif")
        return f"Code {self.code} pour {self.courriel} ({statut})"

    @property
    def est_expire(self) -> bool:
        return timezone.now() > self.date_expiration

    @property
    def est_valide(self) -> bool:
        return (
            not self.est_utilise
            and not self.est_expire
            and self.tentatives_echouees < 5
        )

    def marquer_utilise(self) -> None:
        """Appelée quand le bon code est saisi : le code est consommé et l'adresse est prouvée."""
        self.est_utilise = True
        self.date_verification = timezone.now()
        self.save(update_fields=["est_utilise", "date_verification"])

    def enregistrer_echec(self) -> None:
        self.tentatives_echouees += 1
        self.save(update_fields=["tentatives_echouees"])
