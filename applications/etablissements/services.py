"""Services du domaine Établissement."""

from django.utils.text import slugify

from applications.communs.erreurs import ErreurMetier

from .models import Etablissement


def generer_nom_utilisateur_unique(nom_etablissement: str) -> str:
    """Transforme « Chez Loutcha » en « chez-loutcha » (ou « chez-loutcha-2 » si déjà pris)."""
    base = slugify(nom_etablissement)[:50] or "etablissement"
    candidat, numero = base, 2
    while Etablissement.objects.filter(nom_utilisateur=candidat).exists():
        candidat = f"{base}-{numero}"
        numero += 1
    return candidat


def obtenir_etablissement_du_gerant(utilisateur) -> Etablissement:
    """Renvoie l'établissement géré par l'utilisateur, ou lève une erreur explicite."""
    etablissement = Etablissement.objects.filter(gerant=utilisateur).first()
    if etablissement is None:
        raise ErreurMetier("Aucun établissement n'est associé à votre compte.", code="etablissement_introuvable")
    return etablissement


def obtenir_etablissements_visibles():
    """Établissements visibles du public : uniquement ceux validés par l'administration."""
    return Etablissement.objects.filter(statut_validation="ACTIF")
