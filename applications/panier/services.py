"""
Services du panier.

Appelés par `panier/views.py` et par `commandes/services.py` (création de commande).
"""

from django.db import transaction

from applications.catalogue.models import Plat
from applications.communs.erreurs import ErreurMetier

from .models import LignePanier

QUANTITE_MAX_PAR_LIGNE = 50


def obtenir_lignes_du_client(client):
    return LignePanier.objects.filter(client=client).select_related("plat", "plat__etablissement")


def ajouter_au_panier(client, plat_id: int, quantite: int = 1, instructions: str = "") -> LignePanier:
    """Ajoute un plat (ou augmente sa quantité). Refuse un plat non commandable."""
    plat = Plat.objects.select_related("etablissement").filter(pk=plat_id, est_archive=False).first()
    if plat is None:
        raise ErreurMetier("Ce plat n'existe pas.", code="plat_introuvable")
    if not plat.est_commandable:
        raise ErreurMetier(f"« {plat.nom} » n'est pas disponible pour le moment.", code="plat_indisponible")

    with transaction.atomic():
        ligne, cree = LignePanier.objects.select_for_update().get_or_create(
            client=client, plat=plat, defaults={"quantite": quantite, "instructions_speciales": instructions}
        )
        if not cree:
            ligne.quantite = min(ligne.quantite + quantite, QUANTITE_MAX_PAR_LIGNE)
            if instructions:
                ligne.instructions_speciales = instructions
            ligne.save(update_fields=["quantite", "instructions_speciales"])
    return ligne


def calculer_panier_groupe(client) -> dict:
    """
    Calcule le panier regroupé par établissement, avec des montants recalculés
    à partir des prix ACTUELS des plats (jamais à partir d'un montant envoyé par le frontend).

    Renvoie :
    {
      "paniers_par_etablissement": [
        {"etablissement": <Etablissement>, "lignes": [...], "sous_total_fcfa": 7500,
         "frais_livraison_fcfa": 1000, "total_fcfa": 8500, "est_commandable": True, "avertissements": []}
      ],
      "nombre_total_articles": 3,
      "total_global_fcfa": 8500,
    }
    """
    groupes: dict[int, dict] = {}
    for ligne in obtenir_lignes_du_client(client):
        etablissement = ligne.plat.etablissement
        groupe = groupes.setdefault(etablissement.id, {
            "etablissement": etablissement, "lignes": [], "sous_total_fcfa": 0,
            "avertissements": [], "est_commandable": etablissement.peut_recevoir_commandes,
        })
        groupe["lignes"].append(ligne)
        if ligne.plat.est_commandable:
            groupe["sous_total_fcfa"] += ligne.plat.prix_fcfa * ligne.quantite
        else:
            groupe["avertissements"].append(f"« {ligne.plat.nom} » n'est plus disponible et ne sera pas commandé.")
        if not etablissement.peut_recevoir_commandes and not groupe["avertissements"]:
            groupe["avertissements"].append(f"{etablissement.nom} est actuellement fermé.")

    paniers = []
    for groupe in groupes.values():
        frais = groupe["etablissement"].frais_livraison_fcfa if groupe["sous_total_fcfa"] > 0 else 0
        groupe["frais_livraison_fcfa"] = frais
        groupe["total_fcfa"] = groupe["sous_total_fcfa"] + frais
        groupe["est_commandable"] = groupe["est_commandable"] and groupe["sous_total_fcfa"] > 0
        paniers.append(groupe)

    return {
        "paniers_par_etablissement": paniers,
        "nombre_total_articles": sum(ligne.quantite for groupe in paniers for ligne in groupe["lignes"]),
        "total_global_fcfa": sum(groupe["total_fcfa"] for groupe in paniers),
    }


def vider_panier(client, etablissement_id: int | None = None) -> None:
    """Vide tout le panier, ou seulement la partie d'un établissement (après commande)."""
    lignes = LignePanier.objects.filter(client=client)
    if etablissement_id is not None:
        lignes = lignes.filter(plat__etablissement_id=etablissement_id)
    lignes.delete()
