"""
Tests automatisés pour l'intégration PayTech Sénégal.

Scénarios testés :
1. Initiation d'une tentative de paiement et génération de référence unique.
2. Traitement d'un webhook IPN valide (`sale_complete`) avec transition de la commande vers `CREEE_EN_ATTENTE`.
3. Idempotence : réception répétée d'un même webhook sans effet de bord.
4. Rejet d'un webhook IPN avec signature falsifiée.
5. Gestion d'un événement d'annulation `sale_canceled`.
"""

import hashlib
import hmac
import pytest

from applications.commandes.models import Commande, StatutCommande
from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import ErreurMetier
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.paiements.models import StatutPaiement, TentativePaiement
from applications.paiements.services import (
    initier_demande_paiement_paytech,
    traiter_notification_ipn_paytech,
)
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def commande_a_payer(db):
    client = Utilisateur.objects.create_user(
        courriel="client.pay@ayyou.sn",
        password="Password123!",
        prenom="Awa",
        nom="Fall",
        telephone="+221774445566",
        role=Role.CLIENT,
    )
    gerant = Utilisateur.objects.create_user(
        courriel="gerant.pay@ayyou.sn",
        password="Password123!",
        prenom="Ousmane",
        nom="Sow",
        telephone="+221778889900",
        role=Role.RESTAURANT,
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant,
        type_etablissement=TypeEtablissement.RESTAURANT,
        nom="Saveurs du Saloum",
        nom_utilisateur="saveurs-saloum",
        statut_validation=StatutValidationPartenaire.ACTIF,
        est_ouvert=True,
    )
    commande = Commande.objects.create(
        client=client,
        etablissement=etablissement,
        statut=StatutCommande.EN_ATTENTE_PAIEMENT,
        adresse_livraison="Fann Résidence, Dakar",
        telephone_contact="+221774445566",
        sous_total_fcfa=5000,
        frais_livraison_fcfa=1000,
        total_fcfa=6000,
    )
    return commande


@pytest.mark.django_db
class TestPaiementsPayTech:
    def test_initiation_paiement_paytech(self, commande_a_payer, monkeypatch):
        class ReponseMock:
            status_code = 200

            def json(self):
                return {
                    "success": 1,
                    "token": "tok_paytech_test_123",
                    "redirect_url": "https://paytech.sn/payment/checkout/tok_paytech_test_123",
                }

        monkeypatch.setattr("requests.post", lambda *args, **kwargs: ReponseMock())

        tentative = initier_demande_paiement_paytech(commande_a_payer)

        assert tentative.commande == commande_a_payer
        assert tentative.montant_fcfa == 6000
        assert tentative.statut == StatutPaiement.EN_ATTENTE
        assert tentative.reference_paiement.startswith("PAY-")
        assert tentative.url_redirection != ""

    def test_reception_webhook_ipn_valide(self, commande_a_payer, settings, monkeypatch):
        settings.PAYTECH_CLE_API = "cle_api_test_123"
        settings.PAYTECH_CLE_SECRETE = "cle_secrete_test_456"

        class ReponseMock:
            status_code = 200

            def json(self):
                return {
                    "success": 1,
                    "token": "tok_test_abc",
                    "redirect_url": "https://paytech.sn/payment/checkout/tok_test_abc",
                }

        monkeypatch.setattr("requests.post", lambda *args, **kwargs: ReponseMock())

        tentative = initier_demande_paiement_paytech(commande_a_payer)

        # Calculer le HMAC officiel PayTech
        message = f"{tentative.montant_fcfa}|{tentative.reference_paiement}|{settings.PAYTECH_CLE_API}"
        hmac_calcule = hmac.new(
            settings.PAYTECH_CLE_SECRETE.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        payload_ipn = {
            "type_event": "sale_complete",
            "ref_command": tentative.reference_paiement,
            "item_price": tentative.montant_fcfa,
            "hmac_compute": hmac_calcule,
        }

        tentative_maj = traiter_notification_ipn_paytech(payload_ipn)

        assert tentative_maj.statut == StatutPaiement.CONFIRME
        assert tentative_maj.date_confirmation is not None

        # La commande doit avoir évolué vers CREEE_EN_ATTENTE
        commande_a_payer.refresh_from_db()
        assert commande_a_payer.statut == StatutCommande.CREEE_EN_ATTENTE

    def test_idempotence_webhook_ipn(self, commande_a_payer, settings, monkeypatch):
        settings.PAYTECH_CLE_API = "cle_api_test_123"
        settings.PAYTECH_CLE_SECRETE = "cle_secrete_test_456"

        class ReponseMock:
            status_code = 200

            def json(self):
                return {
                    "success": 1,
                    "token": "tok_test_idemp",
                    "redirect_url": "https://paytech.sn/payment/checkout/tok_test_idemp",
                }

        monkeypatch.setattr("requests.post", lambda *args, **kwargs: ReponseMock())

        tentative = initier_demande_paiement_paytech(commande_a_payer)
        tentative.statut = StatutPaiement.CONFIRME
        tentative.save()

        message = f"{tentative.montant_fcfa}|{tentative.reference_paiement}|{settings.PAYTECH_CLE_API}"
        payload_ipn = {
            "type_event": "sale_complete",
            "ref_command": tentative.reference_paiement,
            "item_price": tentative.montant_fcfa,
            "hmac_compute": hmac.new(
                settings.PAYTECH_CLE_SECRETE.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest(),
        }

        res = traiter_notification_ipn_paytech(payload_ipn)
        assert res.statut == StatutPaiement.CONFIRME

    def test_rejet_webhook_signature_invalide(self, commande_a_payer, settings, monkeypatch):
        settings.PAYTECH_CLE_API = "cle_api_test_123"
        settings.PAYTECH_CLE_SECRETE = "cle_secrete_test_456"

        class ReponseMock:
            status_code = 200

            def json(self):
                return {
                    "success": 1,
                    "token": "tok_test_rej",
                    "redirect_url": "https://paytech.sn/payment/checkout/tok_test_rej",
                }

        monkeypatch.setattr("requests.post", lambda *args, **kwargs: ReponseMock())

        tentative = initier_demande_paiement_paytech(commande_a_payer)

        payload_ipn = {
            "type_event": "sale_complete",
            "ref_command": tentative.reference_paiement,
            "item_price": tentative.montant_fcfa,
            "hmac_compute": "signature_falsifiee_invalide",
            "api_key_sha256": "faux_hash",
            "api_secret_sha256": "faux_hash",
        }

        with pytest.raises(ErreurMetier) as exc:
            traiter_notification_ipn_paytech(payload_ipn)
        assert "Signature cryptographique PayTech invalide" in str(exc.value)

    def test_annulation_paiement_ipn(self, commande_a_payer, settings):
        settings.PAYTECH_CLE_API = ""
        settings.PAYTECH_CLE_SECRETE = ""

        tentative = initier_demande_paiement_paytech(commande_a_payer)

        payload_ipn = {
            "type_event": "sale_canceled",
            "ref_command": tentative.reference_paiement,
        }

        tentative_maj = traiter_notification_ipn_paytech(payload_ipn)
        assert tentative_maj.statut == StatutPaiement.ANNULE
