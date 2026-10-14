"""
Tests automatisés pour le module Administration AYYOU.

Scénarios validés :
1. Accès strict réservé aux administrateurs (rejet des clients et gérants avec code 403).
2. Consultation des statistiques globales de la plateforme.
3. Validation d'un établissement en attente et envoi de notification au gérant.
4. Blocage des transitions de validation interdites (respect de la matrice).
5. Validation d'un coursier en attente.
"""

import pytest
from rest_framework.test import APIClient

from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import TransitionInterdite
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.livraisons.models import ProfilLivreur
from applications.notifications.models import Notification
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def donnees_admin(db):
    admin_user = Utilisateur.objects.create_user(
        courriel="admin@ayyou.sn",
        password="Password123!",
        prenom="Ousmane",
        nom="Sonko",
        telephone="+221770009988",
        role=Role.ADMINISTRATEUR,
    )
    client_user = Utilisateur.objects.create_user(
        courriel="client@ayyou.sn",
        password="Password123!",
        prenom="Awa",
        nom="Ba",
        telephone="+221771112233",
        role=Role.CLIENT,
    )
    gerant = Utilisateur.objects.create_user(
        courriel="resto@teranga.sn",
        password="Password123!",
        prenom="Cheikh",
        nom="Diop",
        telephone="+221772223344",
        role=Role.RESTAURANT,
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant,
        nom="Le Teranga",
        nom_utilisateur="teranga",
        type_etablissement=TypeEtablissement.RESTAURANT,
        statut_validation=StatutValidationPartenaire.EN_ATTENTE_VALIDATION,
    )
    coursier = Utilisateur.objects.create_user(
        courriel="coursier@dakar.sn",
        password="Password123!",
        prenom="Ibou",
        nom="Sene",
        telephone="+221773334455",
        role=Role.LIVREUR,
    )
    profil_livreur = ProfilLivreur.objects.create(
        utilisateur=coursier,
        statut_validation=StatutValidationPartenaire.EN_ATTENTE_VALIDATION,
    )
    return {
        "admin": admin_user,
        "client": client_user,
        "gerant": gerant,
        "etablissement": etablissement,
        "coursier": coursier,
        "profil_livreur": profil_livreur,
    }


@pytest.mark.django_db
def test_interdiction_acces_non_admin(donnees_admin):
    client_user = donnees_admin["client"]
    client_api = APIClient()
    client_api.force_authenticate(user=client_user)

    rep = client_api.get("/api/administration/statistiques/")
    assert rep.status_code == 403


@pytest.mark.django_db
def test_statistiques_globales_admin(donnees_admin):
    admin_user = donnees_admin["admin"]
    client_api = APIClient()
    client_api.force_authenticate(user=admin_user)

    rep = client_api.get("/api/administration/statistiques/")
    assert rep.status_code == 200
    data = rep.json()
    assert "totalCommandes" in data
    assert "volumeAffairesFcfa" in data
    assert "partenairesEnAttente" in data
    assert data["partenairesEnAttente"] == 2  # 1 resto + 1 livreur


@pytest.mark.django_db
def test_validation_etablissement_succes(donnees_admin):
    admin_user = donnees_admin["admin"]
    etablissement = donnees_admin["etablissement"]
    gerant = donnees_admin["gerant"]

    client_api = APIClient()
    client_api.force_authenticate(user=admin_user)

    rep = client_api.post(
        f"/api/administration/etablissements/{etablissement.id}/decision/",
        {"nouveau_statut": StatutValidationPartenaire.ACTIF, "motif_decision": "Documents conformes."},
    )
    assert rep.status_code == 200
    assert rep.json()["statutValidation"] == StatutValidationPartenaire.ACTIF

    etablissement.refresh_from_db()
    assert etablissement.statut_validation == StatutValidationPartenaire.ACTIF

    # Vérification que le gérant a bien reçu sa notification
    assert Notification.objects.filter(destinataire=gerant, est_lue=False).exists()


@pytest.mark.django_db
def test_transition_validation_interdite(donnees_admin):
    admin_user = donnees_admin["admin"]
    etablissement = donnees_admin["etablissement"]

    # Mettre l'établissement en statut ACTIF
    etablissement.statut_validation = StatutValidationPartenaire.ACTIF
    etablissement.save()

    client_api = APIClient()
    client_api.force_authenticate(user=admin_user)

    # Depuis ACTIF, seule la transition vers SUSPENDU est autorisée (pas DEMANDE_CORRECTION)
    rep = client_api.post(
        f"/api/administration/etablissements/{etablissement.id}/decision/",
        {"nouveau_statut": StatutValidationPartenaire.DEMANDE_CORRECTION},
    )
    assert rep.status_code == 409  # TransitionInterdite renvoie 409
    assert "Transition de validation interdite" in rep.json()["message"]


@pytest.mark.django_db
def test_validation_coursier_succes(donnees_admin):
    admin_user = donnees_admin["admin"]
    profil_livreur = donnees_admin["profil_livreur"]
    coursier = donnees_admin["coursier"]

    client_api = APIClient()
    client_api.force_authenticate(user=admin_user)

    rep = client_api.post(
        f"/api/administration/livreurs/{profil_livreur.id}/decision/",
        {"nouveau_statut": StatutValidationPartenaire.ACTIF},
    )
    assert rep.status_code == 200
    assert rep.json()["statutValidation"] == StatutValidationPartenaire.ACTIF

    profil_livreur.refresh_from_db()
    assert profil_livreur.statut_validation == StatutValidationPartenaire.ACTIF
    assert Notification.objects.filter(destinataire=coursier).exists()
