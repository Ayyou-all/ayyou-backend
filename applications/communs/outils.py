"""Petites fonctions utilitaires sans dépendance métier."""

import secrets
import string

from django.http import HttpRequest


def generer_reference(prefixe: str, longueur: int = 8) -> str:
    """Génère une référence lisible et difficile à deviner, ex : 'CMD-7K2P9QXA'."""
    alphabet = string.ascii_uppercase + string.digits
    return f"{prefixe}-" + "".join(secrets.choice(alphabet) for _ in range(longueur))


def generer_code_numerique(longueur: int = 4) -> str:
    """Génère un code PIN numérique (ex : code de livraison à 4 chiffres)."""
    return "".join(secrets.choice(string.digits) for _ in range(longueur))


def construire_url_absolue(requete: HttpRequest | None, fichier) -> str | None:
    """Renvoie l'URL absolue d'un FileField/ImageField, ou None s'il est vide."""
    if not fichier:
        return None
    try:
        url = fichier.url
    except ValueError:
        return None
    return requete.build_absolute_uri(url) if requete else url
