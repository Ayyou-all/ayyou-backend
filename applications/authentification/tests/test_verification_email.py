import pytest
from django.core import mail
from rest_framework.test import APIClient
from applications.authentification.models import CodeVerificationEmail
from applications.utilisateurs.models import Utilisateur
from applications.authentification.services import generer_et_envoyer_code_verification, verifier_code_email
from applications.communs.erreurs import ErreurMetier


@pytest.mark.django_db
class TestVerificationEmailEtInscription:
    def setup_method(self):
        self.client = APIClient()

    def test_envoi_code_verification_succes(self):
        courriel = "testeur.smtp@ayyou.sn"
        resultat = generer_et_envoyer_code_verification(courriel)

        assert resultat["succes"] is True
        assert "Code de vérification envoyé" in resultat["message"]
        assert resultat["expiration_minutes"] == 2

        # Vérification en base de données
        enregistrement = CodeVerificationEmail.objects.filter(courriel=courriel).first()
        assert enregistrement is not None
        assert len(enregistrement.code) == 6
        assert enregistrement.code.isdigit()
        assert enregistrement.est_utilise is False

        # Vérification de l'envoi de l'e-mail via l'outbox Django
        assert len(mail.outbox) >= 1
        dernier_email = mail.outbox[-1]
        assert courriel in dernier_email.to
        assert "AYYOU" in dernier_email.subject
        assert enregistrement.code in dernier_email.subject
        assert enregistrement.code in dernier_email.body
        assert "2 minutes" in dernier_email.body

    def test_verification_code_correct(self):
        courriel = "valide@ayyou.sn"
        generer_et_envoyer_code_verification(courriel)
        enregistrement = CodeVerificationEmail.objects.get(courriel=courriel)

        valide = verifier_code_email(courriel, enregistrement.code)
        assert valide is True

        enregistrement.refresh_from_db()
        assert enregistrement.est_utilise is True

    def test_verification_code_incorrect(self):
        courriel = "invalide@ayyou.sn"
        generer_et_envoyer_code_verification(courriel)

        with pytest.raises(ErreurMetier) as exc_info:
            verifier_code_email(courriel, "000000")
        assert "incorrect" in str(exc_info.value)

    def test_endpoints_api_envoyer_et_verifier_code(self):
        courriel = "api.test@ayyou.sn"

        # 1. Appel POST /api/authentification/envoyer-code/
        reponse_envoi = self.client.post(
            "/api/authentification/envoyer-code/",
            {"courriel": courriel},
            format="json"
        )
        assert reponse_envoi.status_code == 200
        assert reponse_envoi.data["succes"] is True
        assert reponse_envoi.data["expiration_minutes"] == 2

        enregistrement = CodeVerificationEmail.objects.get(courriel=courriel)
        code = enregistrement.code

        # 2. Appel POST /api/authentification/verifier-code/
        reponse_verif = self.client.post(
            "/api/authentification/verifier-code/",
            {"courriel": courriel, "code": code},
            format="json"
        )
        assert reponse_verif.status_code == 200
        assert reponse_verif.data["succes"] is True

        # 3. Appel POST /api/authentification/inscription/ avec mot de passe standard (ex: passer123)
        reponse_inscription = self.client.post(
            "/api/authentification/inscription/",
            {
                "prenom": "Aminata",
                "nom": "Sow",
                "courriel": courriel,
                "telephone": "+221771234567",
                "mot_de_passe": "passer123",
                "confirmation_mot_de_passe": "passer123",
                "role": "CLIENT",
                "adresse": "Point E, Dakar",
                "conditions_acceptees": True
            },
            format="json"
        )
        assert reponse_inscription.status_code == 201
        utilisateur = Utilisateur.objects.filter(courriel=courriel).first()
        assert utilisateur is not None
        assert utilisateur.prenom == "Aminata"
        assert utilisateur.nom == "Sow"
