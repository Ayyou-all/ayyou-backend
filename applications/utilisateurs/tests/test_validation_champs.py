"""
Validation des données saisies : chaque erreur est renvoyée sous le nom du champ concerné,
pour que le frontend affiche le message sous le bon champ (entouré en rouge).
"""

import pytest
from rest_framework.test import APIClient

from applications.commandes.serializers import SerializerCreationCommande
from applications.livraisons.models import ProfilLivreur
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def comptes(db):
    fatou = Utilisateur.objects.create_user(
        courriel="fatou@ayyou.sn", password="MotDePasse!2026", prenom="Fatou", nom="Diop",
        telephone="+221770000001", role=Role.CLIENT,
    )
    moussa = Utilisateur.objects.create_user(
        courriel="moussa@ayyou.sn", password="MotDePasse!2026", prenom="Moussa", nom="Ndiaye",
        telephone="+221770000002", role=Role.LIVREUR,
    )
    ProfilLivreur.objects.create(utilisateur=moussa)
    return {"fatou": fatou, "moussa": moussa}


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.mark.django_db
class TestProfilClient:
    URL = "/api/utilisateurs/moi/"

    def test_courriel_deja_utilise_refuse_sous_le_champ(self, comptes):
        rep = _client(comptes["fatou"]).patch(self.URL, {"courriel": "MOUSSA@ayyou.sn"}, format="json")
        assert rep.status_code == 400
        assert "déjà utilisée" in rep.json()["courriel"][0]

    def test_telephone_invalide_ou_pris(self, comptes):
        client = _client(comptes["fatou"])
        assert "invalide" in client.patch(self.URL, {"telephone": "12ab"}, format="json").json()["telephone"][0]
        rep = client.patch(self.URL, {"telephone": "+221 77 000 00 02"}, format="json")
        assert "déjà utilisé" in rep.json()["telephone"][0]

    def test_prenom_vide_refuse(self, comptes):
        rep = _client(comptes["fatou"]).patch(self.URL, {"prenom": "   "}, format="json")
        assert rep.status_code == 400 and "prenom" in rep.json()

    def test_modification_valide_normalise_le_telephone(self, comptes):
        rep = _client(comptes["fatou"]).patch(
            self.URL, {"telephone": "+221 76 111 22 33", "courriel": "Fatou.Diop@ayyou.sn"}, format="json"
        )
        assert rep.status_code == 200
        comptes["fatou"].refresh_from_db()
        assert comptes["fatou"].telephone == "+221761112233"
        assert comptes["fatou"].courriel == "fatou.diop@ayyou.sn"


@pytest.mark.django_db
class TestChangementMotDePasse:
    URL = "/api/utilisateurs/changer-mot-de-passe/"

    def test_ancien_mot_de_passe_incorrect(self, comptes):
        rep = _client(comptes["fatou"]).post(self.URL, {
            "ancien_mot_de_passe": "faux", "nouveau_mot_de_passe": "Nouveau!2026", "confirmation_mot_de_passe": "Nouveau!2026",
        }, format="json")
        assert rep.status_code == 400 and "ancien_mot_de_passe" in rep.json()

    def test_confirmation_differente_et_mot_de_passe_trop_court(self, comptes):
        client = _client(comptes["fatou"])
        rep = client.post(self.URL, {
            "ancien_mot_de_passe": "MotDePasse!2026", "nouveau_mot_de_passe": "Nouveau!2026", "confirmation_mot_de_passe": "Autre",
        }, format="json")
        assert "confirmation_mot_de_passe" in rep.json()
        rep = client.post(self.URL, {
            "ancien_mot_de_passe": "MotDePasse!2026", "nouveau_mot_de_passe": "abc", "confirmation_mot_de_passe": "abc",
        }, format="json")
        assert "nouveau_mot_de_passe" in rep.json()

    def test_six_caracteres_suffisent_comme_a_l_inscription(self, comptes):
        rep = _client(comptes["fatou"]).post(self.URL, {
            "ancien_mot_de_passe": "MotDePasse!2026", "nouveau_mot_de_passe": "Dakar7", "confirmation_mot_de_passe": "Dakar7",
        }, format="json")
        assert rep.status_code == 200
        comptes["fatou"].refresh_from_db()
        assert comptes["fatou"].check_password("Dakar7")


@pytest.mark.django_db
class TestProfilLivreur:
    URL = "/api/livraisons/profil/"

    def test_erreurs_par_champ_et_rien_n_est_enregistre(self, comptes):
        rep = _client(comptes["moussa"]).patch(self.URL, {
            "prenom": "", "telephone": "+221770000001", "numero_reversement": "abc", "nom_vehicule": "Jakarta",
        }, format="json")
        assert rep.status_code == 400
        assert {"prenom", "telephone", "numero_reversement"} <= set(rep.json())
        comptes["moussa"].refresh_from_db()
        assert comptes["moussa"].prenom == "Moussa"
        assert comptes["moussa"].profil_livreur.nom_vehicule != "Jakarta"

    def test_mot_de_passe_sans_ancien_refuse(self, comptes):
        rep = _client(comptes["moussa"]).patch(self.URL, {"nouveau_mot_de_passe": "Nouveau!2026"}, format="json")
        assert rep.status_code == 400 and "ancien_mot_de_passe" in rep.json()

    def test_modification_valide(self, comptes):
        rep = _client(comptes["moussa"]).patch(self.URL, {
            "prenom": "Moussa", "telephone": "+221 78 999 88 77", "type_vehicule": "moto", "numero_reversement": "77 123 45 67",
        }, format="json")
        assert rep.status_code == 200
        comptes["moussa"].refresh_from_db()
        assert comptes["moussa"].telephone == "+221789998877"
        assert comptes["moussa"].profil_livreur.type_vehicule == "MOTO"
        assert comptes["moussa"].profil_livreur.numero_reversement == "771234567"


def test_commande_telephone_et_adresse_controles(db):
    serializer = SerializerCreationCommande(data={
        "etablissement_id": 1, "adresse_livraison": "   ", "telephone_contact": "pas un numéro",
        "latitude_livraison": 14.69, "longitude_livraison": -17.44,
    })
    assert not serializer.is_valid()
    assert {"adresse_livraison", "telephone_contact"} <= set(serializer.errors)
