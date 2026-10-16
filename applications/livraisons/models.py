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

from applications.communs.choix import StatutValidationPartenaire


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
    date_recuperation = models.DateTimeField(null=True, blank=True)
    date_livraison = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_assignation"]

    def __str__(self) -> str:
        return f"Livraison {self.commande.reference} ({self.etape})"
