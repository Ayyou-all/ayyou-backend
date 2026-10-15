"""
Modèle du panier.

Choix de conception : pas de table « Panier ». Le panier d'un client est
simplement l'ensemble de ses `LignePanier`. Le regroupement par établissement
(le frontend affiche un sous-panier par restaurant) est calculé à la lecture.
Les prix NE sont PAS stockés ici : ils sont toujours relus depuis le plat.
"""

from django.conf import settings
from django.db import models


class LignePanier(models.Model):
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lignes_panier")
    plat = models.ForeignKey("catalogue.Plat", on_delete=models.CASCADE, related_name="lignes_panier")
    quantite = models.PositiveSmallIntegerField(default=1)
    instructions_speciales = models.CharField(max_length=255, blank=True)
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_ajout"]
        constraints = [
            models.UniqueConstraint(fields=["client", "plat"], name="ligne_panier_unique_par_plat"),
            models.CheckConstraint(condition=models.Q(quantite__gte=1, quantite__lte=50), name="ligne_panier_quantite_valide"),
        ]

    def __str__(self) -> str:
        return f"{self.quantite} x {self.plat.nom}"
