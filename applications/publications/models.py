"""
Modèles du domaine Publications pour AYYOU.

Prend en charge :
- Le fil d'accueil vidéo immersif (Reels / TikTok culinaire de restaurants)
- Les publications photo de plats ou de produits
- L'association directe à un plat pour permettre la commande en 1 clic
- Les mentions J'aime (likes), partages et vues
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class TypeMedia(models.TextChoices):
    VIDEO = "VIDEO", "Vidéo culinaire"
    IMAGE = "IMAGE", "Photo de plat ou produit"


class Publication(models.Model):
    etablissement = models.ForeignKey(
        "etablissements.Etablissement",
        on_delete=models.CASCADE,
        related_name="publications",
    )
    plat = models.ForeignKey(
        "catalogue.Plat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="publications",
        help_text="Plat associé mis en valeur dans la vidéo ou photo",
    )
    titre = models.CharField(max_length=150)
    description = models.TextField(blank=True, help_text="Accroche ou description du plat")
    type_media = models.CharField(
        max_length=10,
        choices=TypeMedia.choices,
        default=TypeMedia.VIDEO,
    )
    fichier_media = models.FileField(
        upload_to="publications/medias/",
        help_text="Fichier vidéo MP4 ou image haute définition",
    )
    image_miniature = models.ImageField(
        upload_to="publications/miniatures/",
        blank=True,
        help_text="Image d'affiche (poster de couverture) pour la vidéo",
    )
    duree_secondes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Durée mesurée de la vidéo (300 secondes maximum)",
    )
    nombre_vues = models.PositiveIntegerField(default=0)
    nombre_partages = models.PositiveIntegerField(default=0)
    est_publie = models.BooleanField(default=True, db_index=True)
    date_publication = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-date_publication"]
        indexes = [
            models.Index(fields=["est_publie", "-date_publication"]),
            models.Index(fields=["etablissement", "type_media"]),
        ]

    def __str__(self) -> str:
        return f"{self.titre} ({self.get_type_media_display()}) — {self.etablissement.nom}"


class MentionJeaime(models.Model):
    """Like d'un utilisateur sur une vidéo ou photo."""

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mentions_jeaime",
    )
    publication = models.ForeignKey(
        Publication,
        on_delete=models.CASCADE,
        related_name="mentions_jeaime",
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "publication"],
                name="like_unique_par_utilisateur_et_publication",
            )
        ]

    def __str__(self) -> str:
        return f"Like {self.utilisateur.nom_complet} sur {self.publication.titre}"
