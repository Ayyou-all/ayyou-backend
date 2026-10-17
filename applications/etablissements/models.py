"""
Modèle Établissement : restaurant OU boutique de vendeur.

Restaurant et Vendeur restent deux types distincts (champ `type_etablissement`),
gérés chacun par un utilisateur ayant le rôle correspondant.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.communs.choix import OperateurMobileMoney, StatutValidationPartenaire


class TypeEtablissement(models.TextChoices):
    RESTAURANT = "RESTAURANT", "Restaurant"


def frais_livraison_par_defaut() -> int:
    return settings.FRAIS_LIVRAISON_PAR_DEFAUT_FCFA


class Etablissement(models.Model):
    gerant = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="etablissement")
    type_etablissement = models.CharField(max_length=20, choices=TypeEtablissement.choices, default=TypeEtablissement.RESTAURANT)
    nom = models.CharField(max_length=120)
    nom_utilisateur = models.SlugField(max_length=60, unique=True, help_text="Identifiant public, ex : chezloutcha (@chezloutcha)")
    description = models.TextField(blank=True)
    specialite = models.CharField(max_length=120, blank=True)
    adresse = models.CharField(max_length=255, blank=True)
    quartier_ville = models.CharField(max_length=120, blank=True, db_index=True)
    telephone = models.CharField(max_length=20, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    heure_ouverture = models.TimeField(null=True, blank=True)
    heure_fermeture = models.TimeField(null=True, blank=True)
    # Jours d'ouverture : numéros de jour séparés par des virgules (0 = lundi ... 6 = dimanche)
    jours_ouverture = models.CharField(max_length=20, default="0,1,2,3,4,5,6")
    est_ouvert = models.BooleanField(default=False, help_text="Interrupteur « ouvert/fermé » piloté par le gérant")
    # Coordonnées où le restaurant reçoit l'argent de ses ventes
    numero_reversement = models.CharField(max_length=20, blank=True)
    operateur_reversement = models.CharField(max_length=20, choices=OperateurMobileMoney.choices, blank=True)
    logo = models.ImageField(upload_to="etablissements/logos/", blank=True)
    couverture = models.ImageField(upload_to="etablissements/couvertures/", blank=True)
    frais_livraison_fcfa = models.PositiveIntegerField(default=frais_livraison_par_defaut)
    delai_livraison_texte = models.CharField(max_length=30, default="25-35 min")
    statut_validation = models.CharField(
        max_length=30, choices=StatutValidationPartenaire.choices,
        default=StatutValidationPartenaire.EN_ATTENTE_VALIDATION, db_index=True,
    )
    motif_decision = models.CharField(max_length=255, blank=True, help_text="Motif de correction/suspension communiqué au gérant")
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom"]
        indexes = [models.Index(fields=["statut_validation", "est_ouvert"])]

    def __str__(self) -> str:
        return self.nom

    @property
    def est_actif(self) -> bool:
        return self.statut_validation == StatutValidationPartenaire.ACTIF

    def liste_jours_ouverture(self) -> list[int]:
        return [int(jour) for jour in self.jours_ouverture.split(",") if jour.strip().isdigit()]

    def est_dans_horaires(self, moment=None) -> bool:
        """
        Vrai si le restaurant est dans ses jours et heures d'ouverture.
        Sans horaires renseignés, seul l'interrupteur « ouvert/fermé » du gérant compte.
        Les horaires qui passent minuit (ex : 18h → 2h) sont gérés.
        """
        if self.heure_ouverture is None or self.heure_fermeture is None:
            return True
        maintenant = timezone.localtime(moment)
        if maintenant.weekday() not in self.liste_jours_ouverture():
            return False
        heure = maintenant.time()
        if self.heure_ouverture <= self.heure_fermeture:
            return self.heure_ouverture <= heure < self.heure_fermeture
        return heure >= self.heure_ouverture or heure < self.heure_fermeture

    @property
    def peut_recevoir_commandes(self) -> bool:
        """Règle : validé (ACTIF) + interrupteur ouvert + dans ses horaires d'ouverture."""
        return self.est_actif and self.est_ouvert and self.est_dans_horaires()
