"""
Statistiques d'un restaurant, calculées uniquement à partir des vraies commandes.

Règles de calcul (simples et explicites) :
- une commande « comptée » = payée et non annulée (ni refusée, ni expirée, ni en échec) ;
- le chiffre d'affaires du restaurant = montant des plats (sous-total) moins la commission AYYOU ;
  les frais de livraison ne sont PAS au restaurant ;
- acceptées / refusées / expirées sont lues dans l'historique des statuts ;
- le temps de préparation = fin de préparation − début de préparation.
"""

from datetime import timedelta

from django.db.models import Count, F, Sum
from django.utils import timezone

from .models import Commande, HistoriqueStatutCommande, LigneCommande, StatutCommande

STATUTS_NON_COMPTES = [
    StatutCommande.EN_ATTENTE_PAIEMENT,
    StatutCommande.REFUSEE_ANNULEE,
    StatutCommande.ECHEC_LIVRAISON,
]


def commandes_comptees(etablissement, debut, fin):
    return Commande.objects.filter(etablissement=etablissement, date_creation__gte=debut, date_creation__lt=fin).exclude(
        statut__in=STATUTS_NON_COMPTES
    )


def resume_periode(etablissement, debut, fin) -> dict:
    """Indicateurs principaux d'une période [debut, fin[."""
    commandes = commandes_comptees(etablissement, debut, fin)
    totaux = commandes.aggregate(
        nombre=Count("id"),
        plats=Sum("sous_total_fcfa"),
        commission=Sum("commission_plateforme_fcfa"),
    )
    nombre = totaux["nombre"] or 0
    chiffre_affaires = (totaux["plats"] or 0) - (totaux["commission"] or 0)

    historique = HistoriqueStatutCommande.objects.filter(
        commande__etablissement=etablissement, date_transition__gte=debut, date_transition__lt=fin
    )
    acceptees = historique.filter(nouveau_statut=StatutCommande.EN_PREPARATION).count()
    sorties_sans_acceptation = historique.filter(
        ancien_statut=StatutCommande.CREEE_EN_ATTENTE, nouveau_statut=StatutCommande.REFUSEE_ANNULEE
    )
    refusees = sorties_sans_acceptation.filter(auteur=etablissement.gerant).count()
    expirees = sorties_sans_acceptation.filter(auteur__isnull=True).count()
    recues = acceptees + refusees + expirees

    durees = [
        (c.heure_fin_preparation - c.heure_debut_preparation).total_seconds() / 60
        for c in commandes.filter(heure_debut_preparation__isnull=False, heure_fin_preparation__isnull=False)
    ]

    return {
        "commandes": nombre,
        "chiffre_affaires_fcfa": chiffre_affaires,
        "panier_moyen_fcfa": int(chiffre_affaires / nombre) if nombre else 0,
        "plats_vendus": LigneCommande.objects.filter(commande__in=commandes).aggregate(total=Sum("quantite"))["total"] or 0,
        "clients_uniques": commandes.values("client").distinct().count(),
        "commandes_acceptees": acceptees,
        "commandes_refusees": refusees,
        "commandes_expirees": expirees,
        # None = pas encore de donnée (l'écran affiche « — », jamais une valeur inventée)
        "taux_acceptation_pourcent": round(acceptees * 100 / recues) if recues else None,
        "temps_moyen_preparation_minutes": round(sum(durees) / len(durees)) if durees else None,
        "commandes_via_videos": commandes.exclude(source_video_id="").count(),
        "chiffre_affaires_videos_fcfa": (
            (commandes.exclude(source_video_id="").aggregate(total=Sum("sous_total_fcfa"))["total"] or 0)
            - (commandes.exclude(source_video_id="").aggregate(total=Sum("commission_plateforme_fcfa"))["total"] or 0)
        ),
    }


def evolution_pourcent(actuel, precedent):
    """Comparaison avec la période précédente ; None si la période précédente est vide."""
    if not precedent:
        return None
    return round((actuel - precedent) * 100 / precedent)


def courbe_chiffre_affaires(etablissement, periode: str) -> list:
    """
    Points du graphique des revenus :
    - « 24h » : aujourd'hui, par tranches de 4 heures ;
    - « 7j » / « 30j » : un point par jour sur les 7 / 30 derniers jours.
    """
    maintenant = timezone.localtime()
    debut_jour = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
    points = []
    if periode == "24h":
        for tranche in range(6):
            debut = debut_jour + timedelta(hours=4 * tranche)
            fin = debut + timedelta(hours=4)
            points.append({"libelle": f"{4 * tranche:02d}h-{4 * tranche + 4:02d}h", **_ca_et_nombre(etablissement, debut, fin)})
        return points
    nombre_jours = 30 if periode == "30j" else 7
    for decalage in range(nombre_jours - 1, -1, -1):
        debut = debut_jour - timedelta(days=decalage)
        points.append({"libelle": debut.strftime("%d/%m"), **_ca_et_nombre(etablissement, debut, debut + timedelta(days=1))})
    return points


def _ca_et_nombre(etablissement, debut, fin) -> dict:
    totaux = commandes_comptees(etablissement, debut, fin).aggregate(
        nombre=Count("id"), plats=Sum("sous_total_fcfa"), commission=Sum("commission_plateforme_fcfa")
    )
    return {"commandes": totaux["nombre"] or 0, "chiffre_affaires_fcfa": (totaux["plats"] or 0) - (totaux["commission"] or 0)}


def meilleures_ventes(etablissement, debut, fin, limite: int = 5) -> list:
    """Plats les plus vendus sur la période (quantité et montant)."""
    lignes = (
        LigneCommande.objects.filter(commande__in=commandes_comptees(etablissement, debut, fin))
        .values("nom_plat")
        .annotate(total_quantite=Sum("quantite"), total_montant=Sum(F("prix_unitaire_fcfa") * F("quantite")))
        .order_by("-total_quantite")[:limite]
    )
    return [
        {"nom": ligne["nom_plat"], "quantite": ligne["total_quantite"], "chiffre_affaires_fcfa": ligne["total_montant"]}
        for ligne in lignes
    ]


def statistiques_tableau_de_bord(etablissement, periode: str = "7j") -> dict:
    """Tout ce qu'affiche l'écran « Analytiques » du restaurant."""
    maintenant = timezone.localtime()
    debut_jour = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
    aujourd_hui = resume_periode(etablissement, debut_jour, debut_jour + timedelta(days=1))
    hier = resume_periode(etablissement, debut_jour - timedelta(days=1), debut_jour)
    nombre_jours = {"24h": 1, "7j": 7, "30j": 30}.get(periode, 7)
    debut_periode = debut_jour - timedelta(days=nombre_jours - 1)

    return {
        "aujourdhui": aujourd_hui,
        "evolution_vs_hier": {
            "commandes": evolution_pourcent(aujourd_hui["commandes"], hier["commandes"]),
            "chiffre_affaires": evolution_pourcent(aujourd_hui["chiffre_affaires_fcfa"], hier["chiffre_affaires_fcfa"]),
            "clients": evolution_pourcent(aujourd_hui["clients_uniques"], hier["clients_uniques"]),
        },
        "periode": periode,
        "resume_periode": resume_periode(etablissement, debut_periode, debut_jour + timedelta(days=1)),
        "courbe": courbe_chiffre_affaires(etablissement, periode),
        "courbe_7_jours": courbe_chiffre_affaires(etablissement, "7j"),
        "meilleures_ventes": meilleures_ventes(etablissement, debut_periode, debut_jour + timedelta(days=1)),
    }
