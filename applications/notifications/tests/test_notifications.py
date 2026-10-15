"""
Tests automatisés pour le domaine Notifications AYYOU.
"""

import pytest
from rest_framework.test import APIClient

from applications.notifications.models import Notification, TypeNotification
from applications.notifications.services import (
    compter_notifications_non_lues,
    creer_notification,
)
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def donnees_notifications(db):
    gerant = Utilisateur.objects.create_user(
        courriel="gerant@kebemer.sn",
        password="Password123!",
        prenom="Aliou",
        nom="Sall",
        telephone="+221773334455",
        role=Role.RESTAURANT,
    )
    autre_user = Utilisateur.objects.create_user(
        courriel="client@dakar.sn",
        password="Password123!",
        prenom="Khady",
        nom="Sy",
        telephone="+221774445566",
        role=Role.CLIENT,
    )
    return {"gerant": gerant, "autre": autre_user}


@pytest.mark.django_db
def test_creation_et_lecture_notification(donnees_notifications):
    gerant = donnees_notifications["gerant"]

    notif = creer_notification(
        destinataire=gerant,
        titre="Nouvelle commande #CMD-1234",
        message="2x Thieboudienne Penda Mbaye",
        type_notification=TypeNotification.COMMANDE_NOUVELLE,
        texte_vocal="Nouvelle commande numéro 1234 reçue en cuisine",
        reference_commande="CMD-1234",
    )

    assert notif.est_lue is False
    assert compter_notifications_non_lues(gerant) == 1

    client_api = APIClient()
    client_api.force_authenticate(user=gerant)

    # 1. Vérification de la liste
    reponse = client_api.get("/api/notifications/")
    assert reponse.status_code == 200
    data = reponse.json()
    resultats = data.get("results", data)
    assert len(resultats) == 1
    item = resultats[0]
    assert item["titre"] == "Nouvelle commande #CMD-1234"
    assert item["texteVocal"] == "Nouvelle commande numéro 1234 reçue en cuisine"
    assert item["numeroCommande"] == "CMD-1234"
    assert item["lue"] is False

    # 2. Compteur non lues
    rep_count = client_api.get("/api/notifications/non-lues/count/")
    assert rep_count.json()["nombreNonLues"] == 1

    # 3. Marquer comme lue
    rep_lire = client_api.post(f"/api/notifications/{notif.id}/lire/")
    assert rep_lire.status_code == 200
    assert rep_lire.json()["lue"] is True

    assert compter_notifications_non_lues(gerant) == 0


@pytest.mark.django_db
def test_tout_marquer_lu(donnees_notifications):
    gerant = donnees_notifications["gerant"]

    creer_notification(destinataire=gerant, titre="Alerte 1", message="Message 1")
    creer_notification(destinataire=gerant, titre="Alerte 2", message="Message 2")

    assert compter_notifications_non_lues(gerant) == 2

    client_api = APIClient()
    client_api.force_authenticate(user=gerant)

    rep = client_api.post("/api/notifications/tout-lire/")
    assert rep.status_code == 200
    assert rep.json()["nombreMarquees"] == 2
    assert compter_notifications_non_lues(gerant) == 0


@pytest.mark.django_db
def test_isolation_notifications_inter_utilisateurs(donnees_notifications):
    gerant = donnees_notifications["gerant"]
    autre = donnees_notifications["autre"]

    notif_gerant = creer_notification(destinataire=gerant, titre="Secret cuisine", message="Info gérant")

    client_api = APIClient()
    client_api.force_authenticate(user=autre)

    # L'autre utilisateur ne voit pas la notification
    rep = client_api.get("/api/notifications/")
    resultats = rep.json().get("results", rep.json())
    assert len(resultats) == 0

    # L'autre utilisateur ne peut pas marquer comme lue la notification du gérant
    rep_lire = client_api.post(f"/api/notifications/{notif_gerant.id}/lire/")
    assert rep_lire.status_code == 404
