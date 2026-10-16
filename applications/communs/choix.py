"""Choix (énumérations) partagés par plusieurs applications."""

from django.db import models


class OperateurMobileMoney(models.TextChoices):
    """Opérateur sur lequel un partenaire reçoit ses reversements."""

    WAVE = "WAVE", "Wave"
    ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"


class StatutValidationPartenaire(models.TextChoices):
    """
    Cycle de validation d'un partenaire (restaurant, livreur).

    Règle : un partenaire ne reçoit JAMAIS de commande ou de course tant qu'il
    n'est pas ACTIF (docs/matrice-statuts-transitions.md §2).
    """

    EN_ATTENTE_VALIDATION = "EN_ATTENTE_VALIDATION", "En attente de validation"
    DEMANDE_CORRECTION = "DEMANDE_CORRECTION", "Correction demandée"
    ACTIF = "ACTIF", "Actif"
    SUSPENDU = "SUSPENDU", "Suspendu"
    BANNI = "BANNI", "Banni"


# Transitions de validation autorisées (administration uniquement).
TRANSITIONS_VALIDATION_PARTENAIRE = {
    StatutValidationPartenaire.EN_ATTENTE_VALIDATION: {
        StatutValidationPartenaire.ACTIF,
        StatutValidationPartenaire.DEMANDE_CORRECTION,
        StatutValidationPartenaire.SUSPENDU,
    },
    StatutValidationPartenaire.DEMANDE_CORRECTION: {
        StatutValidationPartenaire.EN_ATTENTE_VALIDATION,
        StatutValidationPartenaire.ACTIF,
    },
    StatutValidationPartenaire.ACTIF: {StatutValidationPartenaire.SUSPENDU},
    StatutValidationPartenaire.SUSPENDU: {
        StatutValidationPartenaire.ACTIF,
        StatutValidationPartenaire.BANNI,
    },
    StatutValidationPartenaire.BANNI: set(),
}
