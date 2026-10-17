"""
Réglages communs à tous les tests pytest du backend.
"""

import pytest


@pytest.fixture(autouse=True)
def hachage_rapide_des_mots_de_passe(settings):
    """
    Pendant les tests uniquement : hachage des mots de passe rapide.
    Le hachage sécurisé (lent par conception) reste celui utilisé en production ;
    sans ce réglage, chaque compte créé dans un test coûte près d'une seconde.
    """
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
