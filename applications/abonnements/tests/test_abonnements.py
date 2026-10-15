"""
Tests automatisés pour le domaine Abonnements AYYOU.
"""

import pytest
from rest_framework.test import APIClient

from applications.abonnements.models import AbonnementEtablissement
from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def donnees_abonnements(db):
    gerant = Utilisateur.objects.create_user(
        courriel="resto@dakar.sn",
        password="Password123!",
        prenom="Awa",
        nom="Fall",
        telephone="+221771234567",
        role=Role.RESTAURANT,
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant,
        nom="Le Thiéboudienne d'Or",
        nom_utilisateur="thiebor",
        type_etablissement=TypeEtablissement.RESTAURANT,
        statut_validation=StatutValidationPartenaire.ACTIF,
    )
    client_user = Utilisateur.objects.create_user(
        courriel="abonne@ayyou.sn",
        password="Password123!",
        prenom="Modou",
        nom="Gueye",
        telephone="+221779876543",
        role=Role.CLIENT,
    )
    return {"gerant": gerant, "etablissement": etablissement, "client": client_user}


@pytest.mark.django_db
def test_basculer_abonnement_cycle_complet(donnees_abonnements):
    client_user = donnees_abonnements["client"]
    etablissement = donnees_abonnements["etablissement"]

    client_api = APIClient()
    client_api.force_authenticate(user=client_user)

    # 1. S'abonner
    rep1 = client_api.post(f"/api/abonnements/{etablissement.id}/basculer/")
    assert rep1.status_code == 200
    assert rep1.json()["estAbonne"] is True
    assert rep1.json()["nombreAbonnes"] == 1
    assert AbonnementEtablissement.objects.filter(utilisateur=client_user, etablissement=etablissement).exists()

    # 2. Se désabonner
    rep2 = client_api.post(f"/api/abonnements/{etablissement.id}/basculer/")
    assert rep2.status_code == 200
    assert rep2.json()["estAbonne"] is False
    assert rep2.json()["nombreAbonnes"] == 0
    assert not AbonnementEtablissement.objects.filter(utilisateur=client_user, etablissement=etablissement).exists()


@pytest.mark.django_db
def test_liste_mes_abonnements(donnees_abonnements):
    client_user = donnees_abonnements["client"]
    etablissement = donnees_abonnements["etablissement"]

    AbonnementEtablissement.objects.create(utilisateur=client_user, etablissement=etablissement)

    client_api = APIClient()
    client_api.force_authenticate(user=client_user)

    reponse = client_api.get("/api/abonnements/mes-abonnements/")
    assert reponse.status_code == 200
    data = reponse.json()
    resultats = data.get("results", data)
    assert len(resultats) == 1
    assert resultats[0]["etablissement"]["nom"] == "Le Thiéboudienne d'Or"


@pytest.mark.django_db
def test_abonnement_anonyme_rejete(donnees_abonnements):
    etablissement = donnees_abonnements["etablissement"]
    client_api = APIClient()

    reponse = client_api.post(f"/api/abonnements/{etablissement.id}/basculer/")
    assert reponse.status_code == 401
