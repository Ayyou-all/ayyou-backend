"""
Modèles du domaine Utilisateur.

- `Utilisateur` : UN SEUL modèle pour tous les rôles (Client, Restaurant,
  Livreur, Administrateur). Le rôle est un champ, pas une table séparée.
- `DocumentJustificatif` : pièces légales des partenaires (RCCM, NINEA, CNI, permis...).

Noms imposés par Django et conservés : `is_active`, `is_staff`, `password`,
`last_login`, `USERNAME_FIELD`, `REQUIRED_FIELDS`, `objects`, `create_user`,
`create_superuser`.
"""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    CLIENT = "CLIENT", "Client"
    RESTAURANT = "RESTAURANT", "Restaurant"
    LIVREUR = "LIVREUR", "Livreur"
    ADMINISTRATEUR = "ADMINISTRATEUR", "Super administrateur"


# Rôles qui gèrent un établissement (catalogue, commandes, publications).
ROLES_GERANTS = {Role.RESTAURANT}
# Rôles qu'un visiteur peut choisir lui-même à l'inscription.
ROLES_INSCRIPTION_PUBLIQUE = {Role.CLIENT, Role.RESTAURANT, Role.LIVREUR}


class GestionnaireUtilisateurs(BaseUserManager):
    """Crée les utilisateurs en utilisant le courriel comme identifiant de connexion."""

    use_in_migrations = True

    def create_user(self, courriel, password=None, **champs):
        if not courriel:
            raise ValueError("Le courriel est obligatoire.")
        utilisateur = self.model(courriel=self.normalize_email(courriel).lower(), **champs)
        utilisateur.set_password(password)  # hachage : le mot de passe n'est jamais stocké en clair
        utilisateur.save(using=self._db)
        return utilisateur

    def create_superuser(self, courriel, password=None, **champs):
        champs.setdefault("role", Role.ADMINISTRATEUR)
        champs.setdefault("is_staff", True)
        champs.setdefault("is_superuser", True)
        return self.create_user(courriel, password, **champs)


class Utilisateur(AbstractBaseUser, PermissionsMixin):
    courriel = models.EmailField("courriel", unique=True)
    telephone = models.CharField("téléphone", max_length=20, unique=True)
    prenom = models.CharField(max_length=80)
    nom = models.CharField(max_length=80)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CLIENT, db_index=True)
    adresse = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(upload_to="photos_profil/", blank=True)
    # Préférences alimentaires explicites, utilisées par les recommandations IA.
    preferences_alimentaires = models.CharField(
        max_length=255, blank=True, help_text="Mots-clés séparés par des virgules, ex : poulet, poisson, végétarien"
    )

    is_active = models.BooleanField("compte actif", default=True)
    is_staff = models.BooleanField("accès admin Django", default=False)
    date_creation = models.DateTimeField(default=timezone.now)

    objects = GestionnaireUtilisateurs()

    USERNAME_FIELD = "courriel"
    EMAIL_FIELD = "courriel"
    REQUIRED_FIELDS = ["prenom", "nom", "telephone"]

    class Meta:
        verbose_name = "utilisateur"
        ordering = ["-date_creation"]

    def __str__(self) -> str:
        return f"{self.prenom} {self.nom} ({self.role})"

    @property
    def nom_complet(self) -> str:
        return f"{self.prenom} {self.nom}".strip()

    @property
    def est_gerant(self) -> bool:
        return self.role in ROLES_GERANTS

    @property
    def est_administrateur(self) -> bool:
        return self.role == Role.ADMINISTRATEUR


class TypeDocument(models.TextChoices):
    RCCM = "RCCM", "Registre de commerce (RCCM)"
    NINEA = "NINEA", "NINEA"
    CNI = "CNI", "Carte nationale d'identité"
    CERTIFICAT_HYGIENE = "CERTIFICAT_HYGIENE", "Autorisation d'exploitation / certificat d'hygiène"
    PERMIS_CONDUIRE = "PERMIS_CONDUIRE", "Permis de conduire"
    CARTE_GRISE = "CARTE_GRISE", "Carte grise"
    ASSURANCE = "ASSURANCE", "Assurance"


class StatutDocument(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de vérification"
    CONFORME = "CONFORME", "Conforme"
    REJETE = "REJETE", "Rejeté"


class DocumentJustificatif(models.Model):
    """Pièce téléversée par un partenaire et vérifiée par l'administration."""

    proprietaire = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, related_name="documents")
    type_document = models.CharField(max_length=30, choices=TypeDocument.choices)
    fichier = models.FileField(upload_to="documents_partenaires/")
    statut = models.CharField(max_length=20, choices=StatutDocument.choices, default=StatutDocument.EN_ATTENTE)
    motif_rejet = models.CharField(max_length=255, blank=True)
    date_envoi = models.DateTimeField(auto_now_add=True)
    date_verification = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_envoi"]

    def __str__(self) -> str:
        return f"{self.get_type_document_display()} — {self.proprietaire}"
