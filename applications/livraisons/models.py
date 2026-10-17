"""
Modèles du domaine Livraison.

- `ProfilLivreur` : informations propres au livreur (véhicule, disponibilité, position).
- `Livraison` : la mission de livraison d'UNE commande.

Le statut de la livraison (`EtapeLivraison`) est distinct du statut de la commande :
il décrit l'avancement de la course du point de vue du livreur. Les deux sont mis
à jour ensemble, dans la même transaction, par `livraisons/services.py`.
"""

from django.conf import settings
from django.db import models

from applications.communs.choix import OperateurMobileMoney, StatutValidationPartenaire


class TypeVehicule(models.TextChoices):
    MOTO = "MOTO", "Moto"
    SCOOTER = "SCOOTER", "Scooter"
    VELO = "VELO", "Vélo"
    VOITURE = "VOITURE", "Voiture"


class DisponibiliteLivreur(models.TextChoices):
    EN_LIGNE = "EN_LIGNE", "En ligne"
    OCCUPE = "OCCUPE", "Occupé (course en cours)"
    HORS_LIGNE = "HORS_LIGNE", "Hors ligne"


class ProfilLivreur(models.Model):
    utilisateur = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profil_livreur")
    type_vehicule = models.CharField(max_length=20, choices=TypeVehicule.choices, default=TypeVehicule.MOTO)
    nom_vehicule = models.CharField(max_length=80, blank=True, help_text="Ex : Yamaha TMAX")
    immatriculation = models.CharField(max_length=30, blank=True)
    zone_principale = models.CharField(max_length=120, blank=True)
    # Coordonnées où le livreur reçoit ses gains
    numero_reversement = models.CharField(max_length=20, blank=True)
    operateur_reversement = models.CharField(max_length=20, choices=OperateurMobileMoney.choices, blank=True)
    statut_validation = models.CharField(
        max_length=30, choices=StatutValidationPartenaire.choices,
        default=StatutValidationPartenaire.EN_ATTENTE_VALIDATION, db_index=True,
    )
    motif_decision = models.CharField(max_length=255, blank=True)
    disponibilite = models.CharField(max_length=20, choices=DisponibiliteLivreur.choices, default=DisponibiliteLivreur.HORS_LIGNE)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    date_derniere_position = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Livreur {self.utilisateur.nom_complet}"

    @property
    def est_valide(self) -> bool:
        """Compte actif ET profil validé par l'administration (ni suspendu, ni banni)."""
        return self.utilisateur.is_active and self.statut_validation == StatutValidationPartenaire.ACTIF

    @property
    def peut_recevoir_courses(self) -> bool:
        """Règle de dispatch : seul un livreur validé ET en ligne reçoit des propositions."""
        return self.est_valide and self.disponibilite == DisponibiliteLivreur.EN_LIGNE


class EtapeLivraison(models.TextChoices):
    VERS_RESTAURANT = "VERS_RESTAURANT", "En route vers l'établissement"
    VERIFICATION_ARTICLES = "VERIFICATION_ARTICLES", "Vérification des articles au comptoir"
    VERS_CLIENT = "VERS_CLIENT", "En route vers le client"
    ARRIVE_CLIENT = "ARRIVE_CLIENT", "Arrivé chez le client"
    LIVREE = "LIVREE", "Livrée"
    ECHOUEE = "ECHOUEE", "Échec de livraison"


class Livraison(models.Model):
    commande = models.OneToOneField("commandes.Commande", on_delete=models.CASCADE, related_name="livraison")
    livreur = models.ForeignKey(ProfilLivreur, on_delete=models.PROTECT, related_name="livraisons")
    etape = models.CharField(max_length=30, choices=EtapeLivraison.choices, default=EtapeLivraison.VERS_RESTAURANT)
    gain_livreur_fcfa = models.PositiveIntegerField(default=0)
    essais_code_echoues = models.PositiveSmallIntegerField(default=0)
    motif_echec = models.CharField(max_length=255, blank=True)
    date_assignation = models.DateTimeField(auto_now_add=True)
    # Renseignée quand le restaurant confirme avoir remis la commande au livreur
    date_remise_restaurant = models.DateTimeField(null=True, blank=True)
    date_recuperation = models.DateTimeField(null=True, blank=True)
    date_livraison = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_assignation"]

    def __str__(self) -> str:
        return f"Livraison {self.commande.reference} ({self.etape})"


class MotifEchecLivraison(models.TextChoices):
    """Raisons possibles d'un échec de livraison (choisies par le livreur)."""

    CLIENT_ABSENT = "CLIENT_ABSENT", "Client absent"
    CLIENT_INJOIGNABLE = "CLIENT_INJOIGNABLE", "Client injoignable"
    ADRESSE_INCORRECTE = "ADRESSE_INCORRECTE", "Adresse incorrecte"
    PROBLEME_VEHICULE = "PROBLEME_VEHICULE", "Problème de véhicule"
    PROBLEME_RESTAURANT = "PROBLEME_RESTAURANT", "Problème avec le restaurant"


class CourseRefusee(models.Model):
    """
    Une course refusée (ou annulée) par un livreur ne lui est plus proposée.
    Les autres livreurs continuent de la voir.
    """

    livreur = models.ForeignKey(ProfilLivreur, on_delete=models.CASCADE, related_name="courses_refusees")
    commande = models.ForeignKey("commandes.Commande", on_delete=models.CASCADE, related_name="refus_livreurs")
    date_refus = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["livreur", "commande"], name="uniq_refus_livreur_commande")]

    def __str__(self) -> str:
        return f"{self.livreur} a refusé {self.commande.reference}"
