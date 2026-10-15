"""
Modèles du domaine Abonnements pour AYYOU.

Permet à un utilisateur (client ou autre rôle) de s'abonner à un restaurant
pour suivre ses nouveautés, ses promotions et ses vidéos de plats.
"""

from django.conf import settings
from django.db import models


class AbonnementEtablissement(models.Model):
    """
    Association entre un utilisateur et un établissement suivi.
    """

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="abonnements_etablissements",
    )
    etablissement = models.ForeignKey(
        "etablissements.Etablissement",
        on_delete=models.CASCADE,
        related_name="abonnements",
    )
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-date_creation"]
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "etablissement"],
                name="abonnement_unique_par_utilisateur_et_etablissement",
            )
        ]

    def __str__(self) -> str:
        return f"{self.utilisateur.nom_complet} abonne a {self.etablissement.nom}"


class LikeEtablissement(models.Model):
    """
    Mention J'aime d'un client envers un restaurant partenaire.
    """

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="likes_etablissements",
    )
    etablissement = models.ForeignKey(
        "etablissements.Etablissement",
        on_delete=models.CASCADE,
        related_name="likes",
    )
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-date_creation"]
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "etablissement"],
                name="like_unique_par_utilisateur_et_etablissement",
            )
        ]

    def __str__(self) -> str:
        return f"{self.utilisateur.nom_complet} aime {self.etablissement.nom}"

