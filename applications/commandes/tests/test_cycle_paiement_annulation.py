"""
Tests de la phase 3 : annulation, remboursement, expirations, paiement robuste et notifications.

PayTech n'est jamais appelé pour de vrai : `requests.post` / `requests.get` sont remplacés
par de fausses réponses (monkeypatch).
"""

import hashlib
import hmac
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from applications.commandes.expirations import traiter_commandes_expirees
from applications.commandes.models import Commande, HistoriqueStatutCommande, StatutCommande
from applications.commandes.services import accepter_commande_par_restaurant, refuser_commande_par_restaurant, transitionner_statut_commande
from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import TransitionInterdite
from applications.etablissements.models import Etablissement
from applications.notifications.models import Notification
from applications.paiements.models import StatutPaiement, TentativePaiement
from applications.paiements.services import initier_demande_paiement_paytech, traiter_notification_ipn_paytech
from applications.utilisateurs.models import Role, Utilisateur

CLE_API = "cle_api_test"
CLE_SECRETE = "cle_secrete_test"


class FausseReponse:
    def __init__(self, donnees, code=200):
        self.donnees = donnees
        self.status_code = code

    def json(self):
        return self.donnees


@pytest.fixture
def paytech(settings, monkeypatch):
    """PayTech configuré + fausses réponses ; renvoie la liste des remboursements demandés."""
    settings.PAYTECH_CLE_API = CLE_API
    settings.PAYTECH_CLE_SECRETE = CLE_SECRETE
    remboursements = []

    def faux_post(url, *args, **kwargs):
        if url.endswith("/refund-payment"):
            remboursements.append(kwargs["data"]["ref_command"])
            return FausseReponse({"success": 1, "refund_id": "RF-1"})
        return FausseReponse({"success": 1, "token": "tok", "redirect_url": "https://paytech.sn/payment/checkout/tok"})

    monkeypatch.setattr("requests.post", faux_post)
    monkeypatch.setattr("requests.get", lambda *a, **k: FausseReponse({"payment": {"state": "pending"}}))
    return remboursements


def notification_ipn(tentative):
    message = f"{tentative.montant_fcfa}|{tentative.reference_paiement}|{CLE_API}"
    return {
        "type_event": "sale_complete",
        "ref_command": tentative.reference_paiement,
        "item_price": tentative.montant_fcfa,
        "hmac_compute": hmac.new(CLE_SECRETE.encode(), message.encode(), hashlib.sha256).hexdigest(),
    }


@pytest.fixture
def acteurs(db):
    client = Utilisateur.objects.create_user(
        courriel="c3@ayyou.sn", password="Password123!", prenom="Fatou", nom="Diop", telephone="+221770003001", role=Role.CLIENT
    )
    gerant = Utilisateur.objects.create_user(
        courriel="g3@ayyou.sn", password="Password123!", prenom="Moussa", nom="Fall", telephone="+221770003002", role=Role.RESTAURANT
    )
    admin = Utilisateur.objects.create_user(
        courriel="a3@ayyou.sn", password="Password123!", prenom="Admin", nom="Ayyou", telephone="+221770003003", role=Role.ADMINISTRATEUR
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant, nom="Chez Fall", nom_utilisateur="chez-fall", statut_validation=StatutValidationPartenaire.ACTIF, est_ouvert=True
    )
    return {"client": client, "gerant": gerant, "admin": admin, "etablissement": etablissement}


def nouvelle_commande(acteurs, statut=StatutCommande.EN_ATTENTE_PAIEMENT):
    return Commande.objects.create(
        client=acteurs["client"], etablissement=acteurs["etablissement"], statut=statut,
        adresse_livraison="Liberté 6", telephone_contact="+221770003001",
        sous_total_fcfa=4000, frais_livraison_fcfa=1000, total_fcfa=5000,
    )


def payer(commande):
    """Simule un paiement confirmé par PayTech."""
    tentative = initier_demande_paiement_paytech(commande)
    traiter_notification_ipn_paytech(notification_ipn(tentative))
    commande.refresh_from_db()
    return tentative


# --- Annulation par le client -----------------------------------------------------


@pytest.mark.django_db
def test_client_annule_une_commande_payee_non_acceptee_et_est_rembourse(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    tentative = payer(commande)
    assert commande.statut == StatutCommande.CREEE_EN_ATTENTE

    api = APIClient()
    api.force_authenticate(acteurs["client"])
    reponse = api.post(f"/api/commandes/{commande.id}/annuler/", {"motif": "Je me suis trompé"}, format="json")

    assert reponse.status_code == 200
    commande.refresh_from_db()
    tentative.refresh_from_db()
    assert commande.statut == StatutCommande.REFUSEE_ANNULEE
    assert tentative.statut == StatutPaiement.REMBOURSE
    assert paytech == [tentative.reference_paiement]


@pytest.mark.django_db
def test_client_ne_peut_plus_annuler_pendant_la_preparation(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    payer(commande)
    accepter_commande_par_restaurant(commande, acteurs["gerant"], delai_minutes=20)

    api = APIClient()
    api.force_authenticate(acteurs["client"])
    reponse = api.post(f"/api/commandes/{commande.id}/annuler/", {}, format="json")
    assert reponse.status_code == 409


# --- Restaurant ---------------------------------------------------------------------


@pytest.mark.django_db
def test_refus_restaurant_rembourse_le_client(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    tentative = payer(commande)
    refuser_commande_par_restaurant(commande, acteurs["gerant"], "Rupture de poisson")

    tentative.refresh_from_db()
    assert tentative.statut == StatutPaiement.REMBOURSE
    assert Notification.objects.filter(destinataire=acteurs["client"], titre="Remboursement effectué").exists()


@pytest.mark.django_db
def test_restaurant_ne_peut_pas_refuser_apres_acceptation(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    payer(commande)
    accepter_commande_par_restaurant(commande, acteurs["gerant"], delai_minutes=20)
    with pytest.raises(TransitionInterdite):
        refuser_commande_par_restaurant(commande, acteurs["gerant"], "Trop de monde")


@pytest.mark.django_db
def test_delai_de_preparation_enregistre_par_l_api(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    payer(commande)
    api = APIClient()
    api.force_authenticate(acteurs["gerant"])
    reponse = api.post(f"/api/commandes/{commande.id}/accepter/", {"delai_minutes": 40}, format="json")
    assert reponse.status_code == 200
    commande.refresh_from_db()
    assert commande.delai_preparation_estime_minutes == 40


# --- Paiement -------------------------------------------------------------------------


@pytest.mark.django_db
def test_une_seule_tentative_active_par_commande(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    premiere = initier_demande_paiement_paytech(commande)
    seconde = initier_demande_paiement_paytech(commande)
    assert premiere.pk == seconde.pk


@pytest.mark.django_db
def test_double_paiement_rembourse(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    premiere = TentativePaiement.objects.create(commande=commande, montant_fcfa=5000)
    seconde = TentativePaiement.objects.create(commande=commande, montant_fcfa=5000)
    traiter_notification_ipn_paytech(notification_ipn(premiere))
    traiter_notification_ipn_paytech(notification_ipn(seconde))

    seconde.refresh_from_db()
    assert seconde.statut == StatutPaiement.REMBOURSE
    assert paytech == [seconde.reference_paiement]


@pytest.mark.django_db
def test_notification_recue_deux_fois_sans_effet(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    tentative = TentativePaiement.objects.create(commande=commande, montant_fcfa=5000)
    traiter_notification_ipn_paytech(notification_ipn(tentative))
    traiter_notification_ipn_paytech(notification_ipn(tentative))
    assert HistoriqueStatutCommande.objects.filter(commande=commande, nouveau_statut=StatutCommande.CREEE_EN_ATTENTE).count() == 1
    assert paytech == []


@pytest.mark.django_db
def test_montant_incorrect_refuse(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    tentative = TentativePaiement.objects.create(commande=commande, montant_fcfa=5000)
    donnees = notification_ipn(tentative)
    donnees["item_price"] = 100
    message = f"100|{tentative.reference_paiement}|{CLE_API}"
    donnees["hmac_compute"] = hmac.new(CLE_SECRETE.encode(), message.encode(), hashlib.sha256).hexdigest()

    traiter_notification_ipn_paytech(donnees)
    tentative.refresh_from_db()
    commande.refresh_from_db()
    assert tentative.statut == StatutPaiement.ECHOUE
    assert commande.statut == StatutCommande.EN_ATTENTE_PAIEMENT


@pytest.mark.django_db
def test_paiement_arrive_apres_annulation_est_rembourse(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    tentative = TentativePaiement.objects.create(commande=commande, montant_fcfa=5000)
    transitionner_statut_commande(commande, StatutCommande.REFUSEE_ANNULEE, auteur=None, motif="Expirée")
    traiter_notification_ipn_paytech(notification_ipn(tentative))
    tentative.refresh_from_db()
    assert tentative.statut == StatutPaiement.REMBOURSE


# --- Expirations -------------------------------------------------------------------


@pytest.mark.django_db
def test_expiration_paiement_apres_15_minutes(acteurs, paytech):
    ancienne = nouvelle_commande(acteurs)
    Commande.objects.filter(pk=ancienne.pk).update(date_creation=timezone.now() - timedelta(minutes=16))
    recente = nouvelle_commande(acteurs)

    traiter_commandes_expirees()
    ancienne.refresh_from_db()
    recente.refresh_from_db()
    assert ancienne.statut == StatutCommande.REFUSEE_ANNULEE
    assert recente.statut == StatutCommande.EN_ATTENTE_PAIEMENT


@pytest.mark.django_db
def test_expiration_acceptation_restaurant_avec_remboursement(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    tentative = payer(commande)
    HistoriqueStatutCommande.objects.filter(commande=commande).update(date_transition=timezone.now() - timedelta(minutes=6))

    traiter_commandes_expirees()
    commande.refresh_from_db()
    tentative.refresh_from_db()
    assert commande.statut == StatutCommande.REFUSEE_ANNULEE
    assert tentative.statut == StatutPaiement.REMBOURSE


@pytest.mark.django_db
def test_alerte_admin_une_seule_fois_si_aucun_livreur(acteurs, paytech):
    commande = nouvelle_commande(acteurs, statut=StatutCommande.PRETE_POUR_RETRAIT)
    Commande.objects.filter(pk=commande.pk).update(heure_fin_preparation=timezone.now() - timedelta(minutes=11))

    traiter_commandes_expirees()
    traiter_commandes_expirees()
    assert Notification.objects.filter(destinataire=acteurs["admin"], reference_commande=commande.reference).count() == 1


# --- Notifications -----------------------------------------------------------------


@pytest.mark.django_db
def test_notifications_a_chaque_etape(acteurs, paytech):
    commande = nouvelle_commande(acteurs)
    payer(commande)
    accepter_commande_par_restaurant(commande, acteurs["gerant"], delai_minutes=20)

    titres_client = list(Notification.objects.filter(destinataire=acteurs["client"]).values_list("titre", flat=True))
    assert "Paiement confirmé" in titres_client
    assert "Commande acceptée" in titres_client
    # Le gérant reçoit la nouvelle commande, mais pas de notification pour sa propre acceptation.
    titres_gerant = list(Notification.objects.filter(destinataire=acteurs["gerant"]).values_list("titre", flat=True))
    assert f"Nouvelle commande {commande.reference}" in titres_gerant
    assert "Commande acceptée" not in titres_gerant
