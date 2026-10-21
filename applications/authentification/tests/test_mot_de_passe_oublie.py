"""
Mot de passe oublié : demande d'un code par e-mail puis choix d'un nouveau mot de passe.
"""

import pytest
from django.core import mail
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from applications.authentification.models import CodeVerificationEmail, TypeActionVerification
from applications.utilisateurs.models import Role, Utilisateur

URL_DEMANDE = "/api/authentification/mot-de-passe-oublie/"
URL_REINITIALISATION = "/api/authentification/reinitialiser-mot-de-passe/"


@pytest.fixture
def compte(db):
    return Utilisateur.objects.create_user(
        courriel="fatou.diop@ayyou.sn",
        password="AncienMotDePasse!2026",
        prenom="Fatou",
        nom="Diop",
        telephone="+221770001122",
        role=Role.CLIENT,
    )


def _dernier_code(courriel):
    return CodeVerificationEmail.objects.filter(
        courriel=courriel, type_action=TypeActionVerification.REINITIALISATION
    ).latest("date_creation")


@pytest.mark.django_db
class TestMotDePasseOublie:
    def setup_method(self):
        self.client = APIClient()

    def test_demande_envoie_un_code_de_reinitialisation(self, compte):
        reponse = self.client.post(URL_DEMANDE, {"courriel": "Fatou.Diop@ayyou.sn"}, format="json")

        assert reponse.status_code == 200
        assert reponse.data["expiration_minutes"] == 10
        code = _dernier_code(compte.courriel)
        assert len(mail.outbox) == 1
        assert code.code in mail.outbox[0].body
        assert "réinitialiser votre mot de passe" in mail.outbox[0].body
        assert "10 minutes" in mail.outbox[0].body

    def test_adresse_inconnue_meme_reponse_sans_email(self, db):
        reponse = self.client.post(URL_DEMANDE, {"courriel": "inconnu@ayyou.sn"}, format="json")

        assert reponse.status_code == 200
        assert "Si un compte actif" in reponse.data["message"]
        assert len(mail.outbox) == 0
        assert not CodeVerificationEmail.objects.exists()

    def test_compte_desactive_ne_recoit_pas_de_code(self, compte):
        compte.is_active = False
        compte.save(update_fields=["is_active"])

        reponse = self.client.post(URL_DEMANDE, {"courriel": compte.courriel}, format="json")

        assert reponse.status_code == 200
        assert len(mail.outbox) == 0

    def test_reinitialisation_change_le_mot_de_passe_et_ferme_les_sessions(self, compte):
        ancien_jeton = RefreshToken.for_user(compte)
        self.client.post(URL_DEMANDE, {"courriel": compte.courriel}, format="json")
        code = _dernier_code(compte.courriel).code

        reponse = self.client.post(URL_REINITIALISATION, {
            "courriel": compte.courriel,
            "code": code,
            "nouveau_mot_de_passe": "NouveauMotDePasse!2026",
            "confirmation_mot_de_passe": "NouveauMotDePasse!2026",
        }, format="json")

        assert reponse.status_code == 200
        compte.refresh_from_db()
        assert compte.check_password("NouveauMotDePasse!2026")
        assert BlacklistedToken.objects.filter(token__jti=ancien_jeton["jti"]).exists()
        connexion = self.client.post("/api/authentification/connexion/", {
            "identifiant": compte.courriel, "mot_de_passe": "NouveauMotDePasse!2026",
        }, format="json")
        assert connexion.status_code == 200

    def test_code_incorrect_refuse(self, compte):
        self.client.post(URL_DEMANDE, {"courriel": compte.courriel}, format="json")

        reponse = self.client.post(URL_REINITIALISATION, {
            "courriel": compte.courriel,
            "code": "000000",
            "nouveau_mot_de_passe": "NouveauMotDePasse!2026",
            "confirmation_mot_de_passe": "NouveauMotDePasse!2026",
        }, format="json")

        assert reponse.status_code == 400
        compte.refresh_from_db()
        assert compte.check_password("AncienMotDePasse!2026")

    def test_code_d_inscription_ne_permet_pas_de_reinitialiser(self, compte):
        from applications.authentification.services import generer_et_envoyer_code_verification

        generer_et_envoyer_code_verification(compte.courriel)  # code de type INSCRIPTION
        code_inscription = CodeVerificationEmail.objects.get(courriel=compte.courriel).code

        reponse = self.client.post(URL_REINITIALISATION, {
            "courriel": compte.courriel,
            "code": code_inscription,
            "nouveau_mot_de_passe": "NouveauMotDePasse!2026",
            "confirmation_mot_de_passe": "NouveauMotDePasse!2026",
        }, format="json")

        assert reponse.status_code == 400

    def test_confirmation_differente_refusee(self, compte):
        self.client.post(URL_DEMANDE, {"courriel": compte.courriel}, format="json")
        code = _dernier_code(compte.courriel).code

        reponse = self.client.post(URL_REINITIALISATION, {
            "courriel": compte.courriel,
            "code": code,
            "nouveau_mot_de_passe": "NouveauMotDePasse!2026",
            "confirmation_mot_de_passe": "Autre!2026",
        }, format="json")

        assert reponse.status_code == 400
        assert "confirmation_mot_de_passe" in str(reponse.data)
