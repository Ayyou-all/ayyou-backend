"""
Modèles du catalogue.

- `CategoriePlat` : catégories de découverte gérées par l'administration
  (ex : Plats sénégalais, Grillades, Boissons) — icônes/couleurs de l'accueil Angular.
- `Plat` : article vendu par un établissement (plat, boisson, dessert, produit).

Les prix sont des entiers en FCFA (le franc CFA n'a pas de centimes).
Un plat n'est jamais supprimé physiquement s'il a été commandé : il est archivé
(`est_archive`) pour préserver l'historique des commandes.
"""

from django.db import models


class CategoriePlat(models.Model):
    nom = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    icone = models.CharField(max_length=60, blank=True, help_text="Classe d'icône, ex : fa-solid fa-bowl-food")
    couleur_fond = models.CharField(max_length=40, blank=True)
    couleur_texte = models.CharField(max_length=40, blank=True)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["ordre", "nom"]
        verbose_name = "catégorie de plat"

    def __str__(self) -> str:
        return self.nom


class SectionMenu(models.TextChoices):
    """Sections du menu utilisées par l'écran « Gérant > Menu »."""

    PLATS_PRINCIPAUX = "PLATS_PRINCIPAUX", "Plats principaux"
    BOISSONS = "BOISSONS", "Boissons"
    DESSERTS = "DESSERTS", "Desserts"


class Plat(models.Model):
    etablissement = models.ForeignKey("etablissements.Etablissement", on_delete=models.CASCADE, related_name="plats")
    categorie = models.ForeignKey(CategoriePlat, on_delete=models.SET_NULL, null=True, blank=True, related_name="plats")
    section_menu = models.CharField(max_length=20, choices=SectionMenu.choices, default=SectionMenu.PLATS_PRINCIPAUX)
    nom = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    prix_fcfa = models.PositiveIntegerField()
    image = models.ImageField(upload_to="plats/", blank=True)
    est_disponible = models.BooleanField(default=True, db_index=True)
    temps_preparation_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    portions = models.PositiveSmallIntegerField(default=1, help_text="Nombre de personnes servies (aide au chatbot budget)")
    est_archive = models.BooleanField(default=False)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["etablissement", "section_menu", "nom"]
        indexes = [models.Index(fields=["etablissement", "est_disponible", "est_archive"])]
        constraints = [models.CheckConstraint(condition=models.Q(prix_fcfa__gt=0), name="plat_prix_strictement_positif")]

    def __str__(self) -> str:
        return f"{self.nom} — {self.etablissement}"

    @property
    def est_commandable(self) -> bool:
        """Un plat est commandable s'il est disponible, non archivé et si l'établissement peut recevoir des commandes."""
        return self.est_disponible and not self.est_archive and self.etablissement.peut_recevoir_commandes
