"""
Tests de la phase 7 : statistiques restaurant et rapport IA calculés sur les vraies commandes.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from applications.commandes.models import Commande, HistoriqueStatutCommande, LigneCommande, StatutCommande
from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def restaurant(db, monkeypatch):
    # Le service IA n'est pas joignable pendant les tests : on teste le calcul local.
    monkeypatch.setattr("applications.intelligence.services.appel_service_ia", lambda *a, **k: None)
    gerant = Utilisateur.objects.create_user(
        courriel="g7@ayyou.sn", password="Password123!", prenom="G", nom="Sept", telephone="+221770007001", role=Role.RESTAURANT
    )
    client = Utilisateur.objects.create_user(
        courriel="c7@ayyou.sn", password="Password123!", prenom="C", nom="Sept", telephone="+221770007002", role=Role.CLIENT
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant, nom="Resto 7", nom_utilisateur="resto-7", statut_validation=StatutValidationPartenaire.ACTIF
    )
    api = APIClient()
    api.force_authenticate(gerant)
    return {"api": api, "gerant": gerant, "client": client, "etablissement": etablissement}


def commande(restaurant, statut, sous_total=4000, commission=0, il_y_a_jours=0, preparation_minutes=None):
    c = Commande.objects.create(
        client=restaurant["client"], etablissement=restaurant["etablissement"], statut=statut,
        adresse_livraison="Yoff", telephone_contact="+221770007002",
        sous_total_fcfa=sous_total, frais_livraison_fcfa=1000, total_fcfa=sous_total + 1000,
        commission_plateforme_fcfa=commission,
    )
    date = timezone.now() - timedelta(days=il_y_a_jours)
    champs = {"date_creation": date}
    if preparation_minutes is not None:
        champs["heure_debut_preparation"] = date
        champs["heure_fin_preparation"] = date + timedelta(minutes=preparation_minutes)
    Commande.objects.filter(pk=c.pk).update(**champs)
    LigneCommande.objects.create(commande=c, nom_plat="Thieb", prix_unitaire_fcfa=sous_total, quantite=1)
    return c


@pytest.mark.django_db
def test_statistiques_du_jour_reelles(restaurant):
    commande(restaurant, StatutCommande.LIVREE, sous_total=4000, commission=400, preparation_minutes=20)
    commande(restaurant, StatutCommande.EN_PREPARATION, sous_total=6000, preparation_minutes=None)
    commande(restaurant, StatutCommande.REFUSEE_ANNULEE, sous_total=9999)  # non comptée
    commande(restaurant, StatutCommande.LIVREE, sous_total=2000, il_y_a_jours=1)  # hier

    donnees = restaurant["api"].get("/api/commandes/restaurant/statistiques/?periode=7j").data
    jour = donnees["aujourdhui"]
    assert jour["commandes"] == 2
    assert jour["chiffre_affaires_fcfa"] == 9600  # (4000 + 6000) − 400 de commission, sans frais de livraison
    assert jour["panier_moyen_fcfa"] == 4800
    assert jour["temps_moyen_preparation_minutes"] == 20
    assert jour["clients_uniques"] == 1
    assert donnees["evolution_vs_hier"]["commandes"] == 100  # 2 aujourd'hui contre 1 hier
    assert len(donnees["courbe"]) == 7
    assert donnees["courbe"][-1]["chiffre_affaires_fcfa"] == 9600


@pytest.mark.django_db
def test_aucune_valeur_inventee_sans_commande(restaurant):
    donnees = restaurant["api"].get("/api/commandes/restaurant/statistiques/").data
    assert donnees["aujourdhui"]["commandes"] == 0
    assert donnees["aujourdhui"]["taux_acceptation_pourcent"] is None
    assert donnees["aujourdhui"]["temps_moyen_preparation_minutes"] is None
    assert donnees["evolution_vs_hier"]["commandes"] is None


@pytest.mark.django_db
def test_taux_d_acceptation_lu_dans_l_historique(restaurant):
    acceptee = commande(restaurant, StatutCommande.EN_PREPARATION)
    refusee = commande(restaurant, StatutCommande.REFUSEE_ANNULEE)
    HistoriqueStatutCommande.objects.create(
        commande=acceptee, ancien_statut="CREEE_EN_ATTENTE", nouveau_statut="EN_PREPARATION", auteur=restaurant["gerant"]
    )
    HistoriqueStatutCommande.objects.create(
        commande=refusee, ancien_statut="CREEE_EN_ATTENTE", nouveau_statut="REFUSEE_ANNULEE", auteur=restaurant["gerant"]
    )
    jour = restaurant["api"].get("/api/commandes/restaurant/statistiques/").data["aujourdhui"]
    assert jour["commandes_acceptees"] == 1
    assert jour["commandes_refusees"] == 1
    assert jour["taux_acceptation_pourcent"] == 50


@pytest.mark.django_db
def test_rapport_ia_donnees_insuffisantes(restaurant):
    commande(restaurant, StatutCommande.LIVREE)
    rapport = restaurant["api"].get("/api/ia/restaurant/rapport-hebdo/").data
    assert rapport["donnees_suffisantes"] is False
    assert rapport["message"] == "Données insuffisantes pour produire une prévision fiable."
    previsions = restaurant["api"].get("/api/ia/restaurant/previsions/").data
    assert previsions["donnees_suffisantes"] is False
    assert previsions["previsions_par_heure"] == []


@pytest.mark.django_db
def test_rapport_ia_avec_assez_de_commandes(restaurant):
    for _ in range(6):
        commande(restaurant, StatutCommande.LIVREE, sous_total=3000, preparation_minutes=15)
    rapport = restaurant["api"].get("/api/ia/restaurant/rapport-hebdo/").data
    assert rapport["donnees_suffisantes"] is True
    assert rapport["statistiques"]["commandes"] == 6
    assert rapport["panier_moyen_fcfa"] == 3000
    assert rapport["plat_star"] == "Thieb"
