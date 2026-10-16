"""
Serializers d'authentification.

Le frontend (interface `FormulaireInscription`) envoie : nom, prenom, courriel,
telephone, mot_de_passe, confirmation_mot_de_passe, role, nom_etablissement,
type_vehicule, adresse, conditions_acceptees.
"""

from django.contrib.auth import password_validation
from rest_framework import serializers

from applications.communs.choix import OperateurMobileMoney
from applications.communs.fichiers import valider_document, valider_image
from applications.livraisons.models import TypeVehicule
from applications.utilisateurs.models import ROLES_GERANTS, ROLES_INSCRIPTION_PUBLIQUE, Role, TypeDocument, Utilisateur


class SerializerInscription(serializers.Serializer):
    prenom = serializers.CharField(max_length=80)
    nom = serializers.CharField(max_length=80)
    courriel = serializers.EmailField()
    telephone = serializers.RegexField(r"^\+?[0-9 ]{9,20}$", error_messages={"invalid": "Numéro de téléphone invalide."})
    mot_de_passe = serializers.CharField(write_only=True, min_length=6)
    confirmation_mot_de_passe = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(choices=[(r.value, r.label) for r in ROLES_INSCRIPTION_PUBLIQUE])
    nom_etablissement = serializers.CharField(max_length=120, required=False, allow_blank=True)
    type_vehicule = serializers.ChoiceField(choices=TypeVehicule.choices, required=False)
    nom_vehicule = serializers.CharField(max_length=80, required=False, allow_blank=True)
    immatriculation = serializers.CharField(max_length=30, required=False, allow_blank=True)
    zone_principale = serializers.CharField(max_length=120, required=False, allow_blank=True)
    photo = serializers.FileField(required=False, allow_null=True, validators=[valider_image])
    adresse = serializers.CharField(max_length=255, required=False, allow_blank=True)
    conditions_acceptees = serializers.BooleanField()
    # Chaque fichier est contrôlé (extension, taille, contenu réel) avant d'être enregistré.
    document_justificatif = serializers.FileField(required=False, allow_null=True, validators=[valider_document])
    document_type = serializers.ChoiceField(choices=TypeDocument.choices, required=False, default=TypeDocument.RCCM)
    logo = serializers.FileField(required=False, allow_null=True, validators=[valider_image])
    couverture = serializers.FileField(required=False, allow_null=True, validators=[valider_image])
    permis_recto = serializers.FileField(required=False, allow_null=True, validators=[valider_document])
    permis_verso = serializers.FileField(required=False, allow_null=True, validators=[valider_document])
    # Restaurant : position réelle, horaires et délai annoncé
    latitude = serializers.FloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, allow_null=True, min_value=-180, max_value=180)
    specialite = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    heure_ouverture = serializers.TimeField(required=False, allow_null=True)
    heure_fermeture = serializers.TimeField(required=False, allow_null=True)
    jours_ouverture = serializers.RegexField(r"^[0-6](,[0-6])*$", required=False, default="0,1,2,3,4,5,6")
    delai_livraison_texte = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    # Livreur (et restaurant) : où recevoir les reversements
    numero_reversement = serializers.RegexField(r"^\+?[0-9 ]{9,20}$", required=False, allow_blank=True, default="")
    operateur_reversement = serializers.ChoiceField(choices=OperateurMobileMoney.choices, required=False, allow_blank=True, default="")

    def validate_courriel(self, courriel):
        courriel = courriel.lower().strip()
        if Utilisateur.objects.filter(courriel=courriel).exists():
            raise serializers.ValidationError("Un compte existe déjà avec ce courriel.")
        from .services import courriel_recemment_verifie

        if not courriel_recemment_verifie(courriel):
            raise serializers.ValidationError("Veuillez d'abord vérifier votre adresse e-mail avec le code reçu.")
        return courriel

    def validate_telephone(self, telephone):
        telephone = telephone.replace(" ", "")
        if Utilisateur.objects.filter(telephone=telephone).exists():
            raise serializers.ValidationError("Un compte existe déjà avec ce numéro.")
        return telephone

    def validate_conditions_acceptees(self, valeur):
        if not valeur:
            raise serializers.ValidationError("Vous devez accepter les conditions d'utilisation.")
        return valeur

    def validate(self, donnees):
        if donnees["mot_de_passe"] != donnees["confirmation_mot_de_passe"]:
            raise serializers.ValidationError({"confirmation_mot_de_passe": "Les mots de passe ne correspondent pas."})
        if donnees["role"] in ROLES_GERANTS and not donnees.get("nom_etablissement", "").strip():
            raise serializers.ValidationError({"nom_etablissement": "Le nom de l'établissement est obligatoire."})
        if donnees["role"] == Role.LIVREUR and not donnees.get("type_vehicule"):
            raise serializers.ValidationError({"type_vehicule": "Le type de véhicule est obligatoire."})
        if donnees["role"] in ROLES_GERANTS:
            # La position du restaurant sert au calcul des frais et au dispatch des livreurs.
            if donnees.get("latitude") is None or donnees.get("longitude") is None:
                raise serializers.ValidationError({"latitude": "La position GPS du restaurant est obligatoire."})
            from applications.livraisons.tarification import valider_eligibilite_zone_livraison

            valider_eligibilite_zone_livraison(donnees["latitude"], donnees["longitude"])
        # Validateurs Django (longueur minimale 6 caractères).
        utilisateur_temporaire = Utilisateur(courriel=donnees["courriel"], prenom=donnees["prenom"], nom=donnees["nom"])
        try:
            password_validation.validate_password(donnees["mot_de_passe"], utilisateur_temporaire)
        except Exception as erreur:  # ValidationError Django -> ValidationError DRF
            messages = list(getattr(erreur, "messages", [str(erreur)]))
            messages_valides = [m for m in messages if "trop courant" not in m.lower() and "common" not in m.lower()]
            if messages_valides:
                raise serializers.ValidationError({"mot_de_passe": messages_valides})
        return donnees


class SerializerConnexion(serializers.Serializer):
    """Le champ `identifiant` accepte le courriel OU le numéro de téléphone (comme l'écran Angular)."""

    identifiant = serializers.CharField()
    mot_de_passe = serializers.CharField(write_only=True)


class SerializerRafraichissement(serializers.Serializer):
    jeton_rafraichissement = serializers.CharField()


class SerializerDemandeCode(serializers.Serializer):
    """Demande d'envoi d'un code de vérification par e-mail via SMTP."""

    courriel = serializers.EmailField()

    def validate_courriel(self, courriel):
        return courriel.lower().strip()


class SerializerVerificationCode(serializers.Serializer):
    """Validation d'un code de vérification e-mail."""

    courriel = serializers.EmailField()
    code = serializers.CharField(min_length=4, max_length=6)

    def validate_courriel(self, courriel):
        return courriel.lower().strip()

    def validate_code(self, code):
        return code.strip()

