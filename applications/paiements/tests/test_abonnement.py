"""
Tests de l'abonnement mensuel des restaurants (14 jours d'essai puis 15 000 FCFA / mois via PayTech).

Vérifie surtout que :
- l'abonnement n'est JAMAIS activé sans confirmation signée de PayTech ;
- un restaurant suspendu ne peut pas contourner la suspension en appelant l'API ;
- un renouvellement ne fait perdre aucun jour ;
- les rappels et avis de suspension ne partent qu'une fois ;
- seuls les paiements confirmés comptent dans les revenus.
"""

import hashlib
import hmac
from datetime import datetime, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement, StatutAbonnement
from applications.notifications.models import Notification, TypeNotification
from applications.paiements.abonnement import (
    ajouter_un_mois,
    initier_paiement_abonnement,
    statistiques_abonnements,
    traiter_echeances_abonnements,
)
from applications.paiements.models import PaiementAbonnement, StatutPaiement
from applications.utilisateurs.models import Role, Utilisateur

CLE_API = "cle_api_test_123"
CLE_SECRETE = "cle_secrete_test_456"


class ReponsePayTech:
    status_code = 200

    def json(self):
        return {"success": 1, "token": "jeton-test", "redirect_url": "https://paytech.sn/payment/checkout/jeton-test"}


@pytest.fixture
def paytech(settings, monkeypatch):
    settings.PAYTECH_CLE_API = CLE_API
    settings.PAYTECH_CLE_SECRETE = CLE_SECRETE
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: ReponsePayTech())


@pytest.fixture
def admin(db):
    return Utilisateur.objects.create_user(
        courriel="admin.abo@ayyou.sn", password="Password123!", prenom="Fatou", nom="Admin",
        telephone="+221770001111", role=Role.ADMINISTRATEUR,
    )


@pytest.fixture
def restaurant(db):
    gerant = Utilisateur.objects.create_user(
        courriel="gerant.abo@ayyou.sn", password="Password123!", prenom="Moussa", nom="Fall",
        telephone="+221770002222", role=Role.RESTAURANT,
    )
    return Etablissement.objects.create(
        gerant=gerant, nom="Chez Abo", nom_utilisateur="chez-abo",
        statut_validation=StatutValidationPartenaire.ACTIF, est_ouvert=True,
    )


def suspendre(etablissement):
    etablissement.date_fin_essai = timezone.now() - timedelta(days=1)
    etablissement.save(update_fields=["date_fin_essai"])


def notification_ipn(paiement, montant=None, type_event="sale_complete"):
    montant = paiement.montant_fcfa if montant is None else montant
    message = f"{montant}|{paiement.reference_paiement}|{CLE_API}"
    return {
        "type_event": type_event,
        "ref_command": paiement.reference_paiement,
        "item_price": montant,
        "payment_method": "Wave",
        "hmac_compute": hmac.new(CLE_SECRETE.encode(), message.encode(), hashlib.sha256).hexdigest(),
    }


def envoyer_ipn(donnees):
    return APIClient().post("/api/paiements/webhook-ipn/", donnees, format="json")


@pytest.mark.django_db
class TestEssaiEtSuspension:
    def test_nouveau_restaurant_a_14_jours_essai(self, restaurant):
        assert restaurant.statut_abonnement == StatutAbonnement.ESSAI
        assert restaurant.jours_restants_abonnement == 14
        assert restaurant.abonnement_valide

    def test_suspendu_ne_peut_pas_contourner_par_l_api(self, restaurant):
        suspendre(restaurant)
        client = APIClient()
        client.force_authenticate(restaurant.gerant)

        reponse = client.get("/api/catalogue/mes-plats/")
        assert reponse.status_code == 403
        assert reponse.data["code"] == "abonnement_requis"
        assert client.patch("/api/etablissements/mon-etablissement/", {"nom": "Pirate"}, format="json").status_code == 403

        # Consultation de son établissement et page abonnement toujours possibles (pour se réactiver)
        reponse = client.get("/api/etablissements/mon-etablissement/")
        assert reponse.status_code == 200
        assert reponse.data["abonnement"]["statut"] == "SUSPENDU"
        assert client.get("/api/paiements/abonnement/").status_code == 200
        restaurant.refresh_from_db()
        assert restaurant.nom == "Chez Abo"  # données conservées

    def test_suspendu_masque_aux_clients(self, restaurant):
        suspendre(restaurant)
        restaurant.refresh_from_db()
        assert not restaurant.peut_recevoir_commandes
        reponse = APIClient().get("/api/etablissements/")
        noms = [resto["nom"] for resto in reponse.data.get("results", reponse.data)]
        assert "Chez Abo" not in noms


@pytest.mark.django_db
class TestPaiementAbonnement:
    def test_initier_ne_suffit_pas_a_activer(self, restaurant, paytech):
        suspendre(restaurant)
        paiement = initier_paiement_abonnement(restaurant)
        assert paiement.url_redirection.startswith("https://paytech.sn")
        assert paiement.montant_fcfa == 15000
        restaurant.refresh_from_db()
        assert restaurant.statut_abonnement == StatutAbonnement.SUSPENDU

    def test_ipn_confirme_active_sans_perdre_les_jours_d_essai(self, restaurant, paytech, admin):
        fin_essai = restaurant.date_fin_essai
        paiement = initier_paiement_abonnement(restaurant)

        assert envoyer_ipn(notification_ipn(paiement)).status_code == 200
        restaurant.refresh_from_db()
        paiement.refresh_from_db()
        assert paiement.statut == StatutPaiement.CONFIRME
        assert paiement.methode_paiement == "Wave"
        assert paiement.date_debut_periode == fin_essai
        assert restaurant.date_fin_abonnement == ajouter_un_mois(fin_essai)
        assert restaurant.statut_abonnement == StatutAbonnement.ACTIF
        assert Notification.objects.filter(destinataire=admin, type_notification=TypeNotification.ABONNEMENT).count() == 1

        # Notification répétée : aucune prolongation supplémentaire
        envoyer_ipn(notification_ipn(paiement))
        restaurant.refresh_from_db()
        assert restaurant.date_fin_abonnement == ajouter_un_mois(fin_essai)

    def test_signature_falsifiee_refusee(self, restaurant, paytech):
        suspendre(restaurant)
        paiement = initier_paiement_abonnement(restaurant)
        donnees = notification_ipn(paiement)
        donnees["hmac_compute"] = "faux"
        assert envoyer_ipn(donnees).status_code == 400
        restaurant.refresh_from_db()
        assert restaurant.statut_abonnement == StatutAbonnement.SUSPENDU

    def test_montant_incorrect_refuse(self, restaurant, paytech):
        suspendre(restaurant)
        paiement = initier_paiement_abonnement(restaurant)
        envoyer_ipn(notification_ipn(paiement, montant=100))
        paiement.refresh_from_db()
        restaurant.refresh_from_db()
        assert paiement.statut == StatutPaiement.ECHOUE
        assert restaurant.statut_abonnement == StatutAbonnement.SUSPENDU

    def test_renouvellement_garde_les_jours_restants(self, restaurant, paytech):
        suspendre(restaurant)
        fin_actuelle = timezone.now() + timedelta(days=5)
        restaurant.date_fin_abonnement = fin_actuelle
        restaurant.save(update_fields=["date_fin_abonnement"])

        paiement = initier_paiement_abonnement(restaurant)
        envoyer_ipn(notification_ipn(paiement))
        restaurant.refresh_from_db()
        assert restaurant.date_fin_abonnement == ajouter_un_mois(fin_actuelle)

    def test_ajouter_un_mois_fin_de_mois(self):
        assert ajouter_un_mois(datetime(2027, 1, 31)) == datetime(2027, 2, 28)
        assert ajouter_un_mois(datetime(2026, 12, 18)) == datetime(2027, 1, 18)


@pytest.mark.django_db
class TestRappelsEtStatistiques:
    def test_rappel_et_suspension_envoyes_une_seule_fois(self, restaurant, admin):
        restaurant.date_fin_essai = timezone.now() + timedelta(days=2)
        restaurant.save(update_fields=["date_fin_essai"])
        traiter_echeances_abonnements()
        traiter_echeances_abonnements()
        rappels = Notification.objects.filter(destinataire=restaurant.gerant, titre="Fin de votre essai gratuit")
        assert rappels.count() == 1
        assert "dans 2 jours" in rappels.first().message

        suspendre(restaurant)
        traiter_echeances_abonnements()
        traiter_echeances_abonnements()
        assert Notification.objects.filter(destinataire=restaurant.gerant, titre="Votre période d'essai est terminée").count() == 1
        assert Notification.objects.filter(destinataire=admin, titre="Fin d'essai sans abonnement").count() == 1

    def test_revenus_uniquement_paiements_confirmes(self, restaurant, admin):
        PaiementAbonnement.objects.create(etablissement=restaurant, montant_fcfa=15000)  # tentative en attente
        PaiementAbonnement.objects.create(
            etablissement=restaurant, montant_fcfa=15000, statut=StatutPaiement.CONFIRME, date_confirmation=timezone.now()
        )
        statistiques = statistiques_abonnements()
        assert statistiques["revenus_cumules"] == 15000
        assert statistiques["revenus_mois"] == 15000
        assert statistiques["nombre_paiements"] == 1
        assert statistiques["en_essai"] == 1

        client = APIClient()
        client.force_authenticate(admin)
        assert client.get("/api/administration/abonnements/statistiques/").status_code == 200
        reponse = client.get("/api/administration/abonnements/?statut=ESSAI")
        assert reponse.data["results"][0]["total_paye_fcfa"] == 15000
        client.force_authenticate(restaurant.gerant)
        assert client.get("/api/administration/abonnements/").status_code == 403
