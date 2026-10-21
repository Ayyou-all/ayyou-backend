"""
Tests automatisés pour la passerelle Django vers l'Intelligence Artificielle AYYOU.

Scénarios validés :
1. Recommandations personnalisées avec microservice IA (intégration nominale).
2. Repli dégradé gracieux (fallback) si le microservice IA est indisponible (garantit 100% d'uptime UX).
3. Chatbot gourmand avec compréhension du budget et cartes de plats réels.
4. Prévisions de flux réservées aux gérants de restaurant.
5. Rapport hebdomadaire managérial.
"""

from unittest.mock import patch
import pytest
from rest_framework.test import APIClient

from applications.catalogue.models import CategoriePlat, Plat
from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def donnees_intelligence(db):
    gerant = Utilisateur.objects.create_user(
        courriel="gerant@almadies.sn",
        password="Password123!",
        prenom="Babacar",
        nom="Sall",
        telephone="+221776667788",
        role=Role.RESTAURANT,
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant,
        nom="Le Lagon Bleu",
        nom_utilisateur="lagonbleu",
        type_etablissement=TypeEtablissement.RESTAURANT,
        statut_validation=StatutValidationPartenaire.ACTIF,
    )
    cat = CategoriePlat.objects.create(nom="Poissons", slug="poissons", ordre=1)
    plat1 = Plat.objects.create(
        etablissement=etablissement,
        categorie=cat,
        nom="Thiof Braisé aux Bananes Plantains",
        prix_fcfa=4500,
        est_disponible=True,
    )
    plat2 = Plat.objects.create(
        etablissement=etablissement,
        categorie=cat,
        nom="Crevettes Sautées à l'Ail",
        prix_fcfa=6000,
        est_disponible=True,
    )

    client_user = Utilisateur.objects.create_user(
        courriel="client@dakar.sn",
        password="Password123!",
        prenom="Amina",
        nom="Fall",
        telephone="+221778889900",
        role=Role.CLIENT,
    )

    return {
        "gerant": gerant,
        "etablissement": etablissement,
        "plat1": plat1,
        "plat2": plat2,
        "client": client_user,
    }


@pytest.mark.django_db
def test_recommandations_avec_service_ia(donnees_intelligence):
    plat1 = donnees_intelligence["plat1"]
    client_api = APIClient()

    reponse_ia_simulee = {
        "recommandations": [
            {
                "id": plat1.id,
                "nom": plat1.nom,
                "nom_restaurant": "Le Lagon Bleu",
                "prix_fcfa": 4500,
                "score_pertinence": 92.5,
                "raison_recommandation": "Spécialité poisson frais du jour",
            }
        ],
        "contexte_moment": "Déjeuner de midi",
        "total": 1,
    }

    with patch("applications.intelligence.services.appel_service_ia", return_value=reponse_ia_simulee):
        rep = client_api.get("/api/ia/recommandations/?budget_max_fcfa=5000")
        assert rep.status_code == 200
        data = rep.json()
        assert data["source"] == "FASTAPI_IA"
        assert len(data["plats"]) == 1
        assert data["plats"][0]["nom"] == "Thiof Braisé aux Bananes Plantains"
        assert data["plats"][0]["scorePertinence"] == 92.5


@pytest.mark.django_db
def test_recommandations_repli_local_si_ia_hors_ligne(donnees_intelligence):
    """En cas de panne ou déconnexion de FastAPI, le backend ne plante jamais et sert un fallback déterministe."""
    client_api = APIClient()

    with patch("applications.intelligence.services.appel_service_ia", return_value=None):
        rep = client_api.get("/api/ia/recommandations/?budget_max_fcfa=5000")
        assert rep.status_code == 200
        data = rep.json()
        assert data["source"] == "REPLI_LOCAL"
        assert len(data["plats"]) == 1  # Seul plat1 <= 5000 FCFA
        assert data["plats"][0]["nom"] == "Thiof Braisé aux Bananes Plantains"


@pytest.mark.django_db
def test_chatbot_avec_cartes_plats(donnees_intelligence):
    plat1 = donnees_intelligence["plat1"]
    client_api = APIClient()

    reponse_ia_simulee = {
        "texte_reponse": "Je vous suggère le délicieux Thiof Braisé sous 5000 FCFA.",
        "plats_suggeres_ids": [plat1.id],
        "budget_respecte": True,
        "intention_detectee": "SUGGESTION",
    }

    with patch("applications.intelligence.services.appel_service_ia", return_value=reponse_ia_simulee):
        rep = client_api.post(
            "/api/ia/chatbot/",
            {"message": "J'ai 5000 FCFA, un bon poisson aux Almadies ?", "budget_fcfa": 5000},
        )
        assert rep.status_code == 200
        data = rep.json()
        assert "Thiof Braisé" in data["texteReponse"]
        assert len(data["plats"]) == 1
        assert data["plats"][0]["id"] == plat1.id


@pytest.mark.django_db
def test_previsions_reservees_gerant(donnees_intelligence):
    client_user = donnees_intelligence["client"]
    gerant = donnees_intelligence["gerant"]

    client_api = APIClient()

    # Rejet client (403)
    client_api.force_authenticate(user=client_user)
    rep_client = client_api.get("/api/ia/restaurant/previsions/")
    assert rep_client.status_code == 403

    # Succès gérant (200)
    client_api.force_authenticate(user=gerant)
    rep_gerant = client_api.get("/api/ia/restaurant/previsions/")
    assert rep_gerant.status_code == 200
    assert "previsions_par_heure" in rep_gerant.json()


@pytest.mark.django_db
def test_rapport_hebdomadaire_gerant(donnees_intelligence):
    gerant = donnees_intelligence["gerant"]
    client_api = APIClient()
    client_api.force_authenticate(user=gerant)

    rep = client_api.get("/api/ia/restaurant/rapport-hebdo/")
    assert rep.status_code == 200
    data = rep.json()
    # Sans historique suffisant : aucun chiffre ni conseil inventé
    assert data["donnees_suffisantes"] is False
    assert data["message"] == "Données insuffisantes pour produire une prévision fiable."


# ---------------------------------------------------------------------------
# Recherche vocale
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_recherche_vocale_transmet_les_quartiers_reels_au_service_ia(donnees_intelligence):
    etablissement = Etablissement.objects.get(nom_utilisateur="lagonbleu")
    etablissement.quartier_ville = "Almadies"
    etablissement.save(update_fields=["quartier_ville"])
    reponse_ia_simulee = {
        "texte_normalise": "un thiof aux almadies",
        "specialites": ["poisson"],
        "termes_recherche": ["poisson", "thiof"],
        "mots_libres": [],
        "budget_max_fcfa": None,
        "quartier": "Almadies",
        "tri": None,
        "ouvert_seulement": False,
    }

    with patch("applications.intelligence.services.appel_service_ia", return_value=reponse_ia_simulee) as appel:
        rep = APIClient().post("/api/ia/recherche-vocale/", {"texte": "Un thiof aux Almadies"}, format="json")

    assert rep.status_code == 200
    assert rep.json()["source"] == "FASTAPI_IA"
    assert rep.json()["quartier"] == "Almadies"
    assert appel.call_args.args[1] == {"texte": "Un thiof aux Almadies", "quartiers_connus": ["Almadies"]}


@pytest.mark.django_db
def test_recherche_vocale_repli_si_service_ia_injoignable(db):
    with patch("applications.intelligence.services.appel_service_ia", return_value=None):
        rep = APIClient().post("/api/ia/recherche-vocale/", {"texte": "Chez Loutcha, vite !"}, format="json")

    assert rep.status_code == 200
    assert rep.json()["source"] == "REPLI_LOCAL"
    assert rep.json()["mots_libres"] == ["chez", "loutcha", "vite"]


@pytest.mark.django_db
def test_recherche_vocale_texte_vide_refuse(db):
    assert APIClient().post("/api/ia/recherche-vocale/", {"texte": ""}, format="json").status_code == 400
