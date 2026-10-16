"""
Tests de la phase 2 (cohérence frontend ↔ backend).

1. Le total estimé avant paiement est exactement le total de la commande créée.
2. La position de livraison est obligatoire.
3. Un restaurant hors de ses horaires ne reçoit pas de commande.
4. Le panier ne renvoie plus de frais de livraison fictifs.
5. La liste « Mes commandes » est paginée (count / results).
"""

from datetime import time

import pytest
from rest_framework.test import APIClient

from applications.catalogue.models import Plat
from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement
from applications.utilisateurs.models import Role, Utilisateur

POSITION_MERMOZ = {"latitude_livraison": 14.71, "longitude_livraison": -17.47}


@pytest.fixture
def contexte(db):
    client = Utilisateur.objects.create_user(
        courriel="client.estim@ayyou.sn", password="Password123!", prenom="Awa", nom="Sy",
        telephone="+221770009001", role=Role.CLIENT,
    )
    gerant = Utilisateur.objects.create_user(
        courriel="gerant.estim@ayyou.sn", password="Password123!", prenom="Ali", nom="Ba",
        telephone="+221770009002", role=Role.RESTAURANT,
    )
    restaurant = Etablissement.objects.create(
        gerant=gerant, nom="Le Plateau", nom_utilisateur="le-plateau",
        statut_validation=StatutValidationPartenaire.ACTIF, est_ouvert=True,
        latitude=14.67, longitude=-17.43,
    )
    plat = Plat.objects.create(etablissement=restaurant, nom="Yassa", prix_fcfa=3000)
    api = APIClient()
    api.force_authenticate(client)
    return {"api": api, "restaurant": restaurant, "plat": plat}


def payload(contexte, **autres):
    return {
        "etablissement_id": contexte["restaurant"].id,
        "articles": [{"plat_id": contexte["plat"].id, "quantite": 2}],
        **POSITION_MERMOZ,
        **autres,
    }


@pytest.mark.django_db
def test_estimation_identique_au_total_de_la_commande(contexte):
    api = contexte["api"]
    estimation = api.post("/api/commandes/estimation/", payload(contexte), format="json")
    assert estimation.status_code == 200
    assert estimation.data["sous_total_fcfa"] == 6000

    commande = api.post("/api/commandes/", payload(contexte, adresse_livraison="Mermoz", repere_livraison="Portail bleu"), format="json")
    assert commande.status_code == 201
    assert commande.data["total_fcfa"] == estimation.data["total_fcfa"]
    assert commande.data["frais_livraison_fcfa"] == estimation.data["frais_livraison_fcfa"]
    assert commande.data["repere_livraison"] == "Portail bleu"


@pytest.mark.django_db
def test_position_de_livraison_obligatoire(contexte):
    donnees = payload(contexte, adresse_livraison="Mermoz")
    del donnees["latitude_livraison"]
    reponse = contexte["api"].post("/api/commandes/", donnees, format="json")
    assert reponse.status_code == 400
    assert "latitude_livraison" in reponse.data


@pytest.mark.django_db
def test_restaurant_hors_horaires_ne_recoit_pas_de_commande(contexte):
    restaurant = contexte["restaurant"]
    # Ouvert seulement une minute en pleine nuit : il est (presque) toujours fermé pendant le test.
    restaurant.heure_ouverture = time(3, 0)
    restaurant.heure_fermeture = time(3, 1)
    restaurant.save()

    reponse = contexte["api"].post("/api/commandes/", payload(contexte, adresse_livraison="Mermoz"), format="json")
    assert reponse.status_code == 400
    assert reponse.data["code"] == "etablissement_ferme"


@pytest.mark.django_db
def test_jours_et_horaires_qui_passent_minuit(contexte):
    from datetime import datetime

    from django.utils import timezone

    restaurant = contexte["restaurant"]
    restaurant.heure_ouverture = time(18, 0)
    restaurant.heure_fermeture = time(2, 0)
    restaurant.jours_ouverture = "0,1,2,3,4,5,6"
    lundi_23h = timezone.make_aware(datetime(2026, 10, 12, 23, 0))
    mardi_15h = timezone.make_aware(datetime(2026, 10, 13, 15, 0))
    assert restaurant.est_dans_horaires(lundi_23h) is True
    assert restaurant.est_dans_horaires(mardi_15h) is False

    restaurant.jours_ouverture = "1"  # mardi seulement
    assert restaurant.est_dans_horaires(lundi_23h) is False


@pytest.mark.django_db
def test_panier_sans_frais_fictifs(contexte):
    api = contexte["api"]
    api.post("/api/panier/lignes/", {"plat_id": contexte["plat"].id, "quantite": 1}, format="json")
    panier = api.get("/api/panier/").data
    groupe = panier["paniers_par_etablissement"][0]
    assert groupe["sous_total_fcfa"] == 3000
    assert "frais_livraison_fcfa" not in groupe


@pytest.mark.django_db
def test_mes_commandes_paginees(contexte):
    api = contexte["api"]
    api.post("/api/commandes/", payload(contexte, adresse_livraison="Mermoz"), format="json")
    reponse = api.get("/api/commandes/")
    assert reponse.data["count"] == 1
    assert len(reponse.data["results"]) == 1
