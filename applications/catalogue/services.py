"""Services du catalogue (requêtes réutilisées par panier, commandes et IA)."""

from django.db.models import Count, Q, QuerySet

from .models import Plat


def obtenir_plats_visibles() -> QuerySet:
    """Plats non archivés d'établissements validés (ACTIF). Les indisponibles restent visibles mais grisés."""
    return (
        Plat.objects.filter(est_archive=False, etablissement__statut_validation="ACTIF")
        .select_related("etablissement", "categorie")
    )


def obtenir_plats_disponibles() -> QuerySet:
    """Plats réellement commandables maintenant (disponible + établissement ouvert)."""
    return obtenir_plats_visibles().filter(est_disponible=True, etablissement__est_ouvert=True)


def annoter_nombre_commandes(plats: QuerySet) -> QuerySet:
    """Ajoute `nombre_commandes` (commandes payées) — utilisé pour les badges « populaire »."""
    return plats.annotate(
        nombre_commandes=Count(
            "lignes_commande",
            filter=~Q(lignes_commande__commande__statut__in=["EN_ATTENTE_PAIEMENT", "ANNULEE"]),
            distinct=True,
        )
    )


def filtrer_plats(plats: QuerySet, parametres) -> QuerySet:
    """Applique les filtres d'URL : etablissement, categorie, recherche, prix_max, disponibles."""
    if (etablissement := parametres.get("etablissement", "")).isdigit():
        plats = plats.filter(etablissement_id=int(etablissement))
    if categorie := parametres.get("categorie"):
        plats = plats.filter(categorie_id=int(categorie)) if categorie.isdigit() else plats.filter(categorie__slug=categorie)
    if recherche := parametres.get("recherche"):
        plats = plats.filter(Q(nom__icontains=recherche) | Q(description__icontains=recherche))
    if (prix_max := parametres.get("prix_max")) and prix_max.isdigit():
        plats = plats.filter(prix_fcfa__lte=int(prix_max))
    if parametres.get("disponibles") == "1":
        plats = plats.filter(est_disponible=True, etablissement__est_ouvert=True)
    return plats
