"""
Modèles du domaine Commande pour AYYOU.

Ce domaine gère le cycle de vie complet d'une commande :
- Création à partir d'un panier validé
- Lignes de commande avec snapshot immuable des prix et des noms
- Machine à états formelle et historique d'audit de chaque transition
- Code PIN de livraison sécurisé à 4 chiffres

Règles de cohérence :
1. Les prix et totaux sont recalculés et verrouillés côté serveur.
2. Un code PIN de 4 chiffres est généré à la création pour la remise finale.
3. Chaque transition de statut est consignée dans HistoriqueStatutCommande.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from applications.communs.outils import generer_code_numerique, generer_reference


class ModePaiement(models.TextChoices):
    WAVE = "WAVE", "Wave Sénégal"
    ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"


class StatutCommande(models.TextChoices):
    """
    États officiels du cycle de vie de la commande AYYOU
    (conforme à docs/matrice-statuts-transitions.md).
    """

    EN_ATTENTE_PAIEMENT = "EN_ATTENTE_PAIEMENT", "En attente de paiement"
    CREEE_EN_ATTENTE = "CREEE_EN_ATTENTE", "Payée, en attente d'acceptation par le restaurant"
    EN_PREPARATION = "EN_PREPARATION", "En préparation en cuisine"
    PRETE_POUR_RETRAIT = "PRETE_POUR_RETRAIT", "Prête pour retrait coursier"
    COURSE_ASSIGNEE = "COURSE_ASSIGNEE", "Course acceptée par un livreur"
    EN_VERIFICATION = "EN_VERIFICATION", "Livreur au restaurant, vérification des articles"
    EN_LIVRAISON = "EN_LIVRAISON", "En cours de livraison vers le client"
    ARRIVE_CLIENT = "ARRIVE_CLIENT", "Livreur arrivé à l'adresse de livraison"
    LIVREE = "LIVREE", "Commande livrée (PIN validé)"
    REFUSEE_ANNULEE = "REFUSEE_ANNULEE", "Refusée ou annulée"
    ECHEC_LIVRAISON = "ECHEC_LIVRAISON", "Échec de livraison"


# Statuts où la commande est encore active / en cours
STATUTS_COMMANDES_EN_COURS = {
    StatutCommande.EN_ATTENTE_PAIEMENT,
    StatutCommande.CREEE_EN_ATTENTE,
    StatutCommande.EN_PREPARATION,
    StatutCommande.PRETE_POUR_RETRAIT,
    StatutCommande.COURSE_ASSIGNEE,
    StatutCommande.EN_VERIFICATION,
    StatutCommande.EN_LIVRAISON,
    StatutCommande.ARRIVE_CLIENT,
}


def generer_reference_commande() -> str:
    return generer_reference("ORD")


def generer_code_livraison_pin() -> str:
    """
    Génère un code PIN à 4 chiffres sécurisé, avec garantie d'absence de collision
    parmi les commandes actuellement actives. Interdit formellement '0000'.
    """
    try:
        from django.apps import apps
        CommandeModel = apps.get_model("commandes", "Commande")
        for _ in range(50):
            code = generer_code_numerique(4)
            if code == "0000":
                continue
            if not CommandeModel.objects.filter(
                code_livraison_pin=code,
                statut__in=STATUTS_COMMANDES_EN_COURS,
            ).exists():
                return code
        return generer_code_numerique(6)
    except Exception:
        code = generer_code_numerique(4)
        return code if code != "0000" else "1234"


class Commande(models.Model):
    reference = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        default=generer_reference_commande,
        help_text="Référence publique unique de la commande (ex: ORD-99238)",
    )
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="commandes_client",
    )
    etablissement = models.ForeignKey(
        "etablissements.Etablissement",
        on_delete=models.PROTECT,
        related_name="commandes_etablissement",
    )
    statut = models.CharField(
        max_length=30,
        choices=StatutCommande.choices,
        default=StatutCommande.EN_ATTENTE_PAIEMENT,
        db_index=True,
    )
    mode_paiement = models.CharField(
        max_length=20,
        choices=ModePaiement.choices,
        default=ModePaiement.WAVE,
    )

    # Coordonnées et livraison
    adresse_livraison = models.CharField(max_length=255)
    repere_livraison = models.CharField(
        max_length=255, blank=True, help_text="Point de repère, ex : derrière la mosquée, portail bleu"
    )
    telephone_contact = models.CharField(max_length=30)
    instructions_livraison = models.TextField(blank=True)
    latitude_livraison = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude_livraison = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Montants verrouillés en FCFA (sans centimes)
    sous_total_fcfa = models.PositiveIntegerField()
    frais_livraison_fcfa = models.PositiveIntegerField()
    total_fcfa = models.PositiveIntegerField()

    # Code de sécurité à 4 chiffres remis au client et saisi par le livreur
    code_livraison_pin = models.CharField(
        max_length=4,
        default=generer_code_livraison_pin,
        help_text="Code PIN à 4 chiffres pour validation de la remise",
    )

    # Délais et motifs
    delai_preparation_estime_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    heure_debut_preparation = models.DateTimeField(null=True, blank=True)
    heure_fin_preparation = models.DateTimeField(null=True, blank=True)
    heure_depart_livraison = models.DateTimeField(null=True, blank=True)
    heure_livraison_effective = models.DateTimeField(null=True, blank=True)
    motif_refus_ou_annulation = models.CharField(max_length=255, blank=True)

    # Attribution marketing / Studio vidéo
    source_video_id = models.CharField(max_length=64, blank=True)

    # Horodatages
    date_creation = models.DateTimeField(default=timezone.now, db_index=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_creation"]
        indexes = [
            models.Index(fields=["client", "-date_creation"]),
            models.Index(fields=["etablissement", "statut"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["code_livraison_pin"],
                # Liste triée (et non un ensemble) pour que les migrations restent stables.
                condition=models.Q(statut__in=sorted(STATUTS_COMMANDES_EN_COURS)),
                name="uniq_pin_commande_active",
            )
        ]

    def __str__(self) -> str:
        return f"{self.reference} ({self.get_statut_display()}) — {self.total_fcfa} FCFA"

    @property
    def est_en_cours(self) -> bool:
        return self.statut in STATUTS_COMMANDES_EN_COURS


class LigneCommande(models.Model):
    """
    Ligne d'article au sein de la commande.
    Conserve le nom et le prix du plat au moment exact de l'achat.
    """

    commande = models.ForeignKey(
        Commande,
        on_delete=models.CASCADE,
        related_name="lignes",
    )
    plat = models.ForeignKey(
        "catalogue.Plat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lignes_commande",
    )
    nom_plat = models.CharField(max_length=120)
    prix_unitaire_fcfa = models.PositiveIntegerField()
    quantite = models.PositiveSmallIntegerField(default=1)
    instructions_speciales = models.CharField(max_length=255, blank=True)
    est_verifie_par_livreur = models.BooleanField(
        default=False,
        help_text="Pointage effectué par le coursier au guichet du restaurant",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.quantite}x {self.nom_plat} ({self.total_ligne_fcfa} FCFA)"

    @property
    def total_ligne_fcfa(self) -> int:
        return self.prix_unitaire_fcfa * self.quantite


class HistoriqueStatutCommande(models.Model):
    """
    Journal d'audit de toutes les transitions d'état d'une commande.
    Permet une traçabilité totale entre Client, Restaurant, Livreur et Administrateur.
    """

    commande = models.ForeignKey(
        Commande,
        on_delete=models.CASCADE,
        related_name="historique_statuts",
    )
    ancien_statut = models.CharField(max_length=30)
    nouveau_statut = models.CharField(max_length=30)
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    commentaire = models.CharField(max_length=255, blank=True)
    date_transition = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["date_transition"]

    def __str__(self) -> str:
        return f"{self.commande.reference} : {self.ancien_statut} -> {self.nouveau_statut}"
