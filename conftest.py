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


@pytest.fixture(autouse=True)
def dossier_medias_temporaire(settings, tmp_path):
    """Les fichiers envoyés pendant les tests vont dans un dossier jetable, jamais dans le vrai dossier medias/."""
    settings.MEDIA_ROOT = tmp_path / "medias"


@pytest.fixture(autouse=True)
def compteurs_de_limitation_remis_a_zero():
    """Chaque test repart avec des compteurs de limitation de débit vides (sinon ils s'accumulent d'un test à l'autre)."""
    from django.core.cache import cache

    cache.clear()
