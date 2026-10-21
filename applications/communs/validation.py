"""
Règles de validation partagées (téléphone, champs texte obligatoires).

Les erreurs sont levées champ par champ ({"telephone": ["..."]}) : le frontend
affiche le message sous le bon champ et l'entoure en rouge.
"""

import re

from rest_framework import serializers

# Numéro sénégalais ou international : chiffres, espaces facultatifs, « + » en tête autorisé (9 à 20 caractères).
REGEX_TELEPHONE = re.compile(r"^\+?[0-9 ]{9,20}$")
MESSAGE_TELEPHONE_INVALIDE = "Numéro de téléphone invalide (ex. : +221 77 123 45 67)."


def normaliser_telephone(valeur: str) -> str:
    """Contrôle le format puis retire les espaces : « +221 77 123 45 67 » -> « +221771234567 »."""
    valeur = (valeur or "").strip()
    if not REGEX_TELEPHONE.match(valeur):
        raise serializers.ValidationError(MESSAGE_TELEPHONE_INVALIDE)
    return valeur.replace(" ", "")


def valider_telephone_unique(valeur: str, utilisateur_actuel=None) -> str:
    """Téléphone au bon format et pas déjà utilisé par un autre compte."""
    from applications.utilisateurs.models import Utilisateur

    telephone = normaliser_telephone(valeur)
    autres = Utilisateur.objects.filter(telephone=telephone)
    if utilisateur_actuel is not None:
        autres = autres.exclude(pk=utilisateur_actuel.pk)
    if autres.exists():
        raise serializers.ValidationError("Ce numéro est déjà utilisé par un autre compte.")
    return telephone


def texte_obligatoire(valeur: str, message: str = "Ce champ est obligatoire.") -> str:
    """Refuse un texte vide ou composé uniquement d'espaces."""
    valeur = (valeur or "").strip()
    if not valeur:
        raise serializers.ValidationError(message)
    return valeur


def valider_nouveau_mot_de_passe(mot_de_passe: str, utilisateur=None) -> str:
    """Mêmes règles qu'à l'inscription (validateurs Django, 6 caractères minimum)."""
    from django.contrib.auth import password_validation
    from django.core.exceptions import ValidationError as ErreurValidationDjango

    try:
        password_validation.validate_password(mot_de_passe, utilisateur)
    except ErreurValidationDjango as erreur:
        messages = [m for m in erreur.messages if "trop courant" not in m.lower() and "common" not in m.lower()]
        if messages:
            raise serializers.ValidationError(messages)
    return mot_de_passe
