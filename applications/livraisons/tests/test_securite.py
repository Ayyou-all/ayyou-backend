"""
Tests de sécurité (Phase 1 de la correction après audit).

1. Un livreur ne peut pas terminer la commande d'un autre livreur.
2. Un livreur non validé ne reçoit aucune course et ne peut pas passer en ligne.
3. Une course proposée ne révèle pas les données personnelles du client.
4. Un document justificatif n'est lisible que par son propriétaire ou un admin.
5. Les médias privés et les fichiers dangereux ne sont pas servis par /medias/.
6. Une fausse notification PayTech (sans clés ou sans signature) est refusée.
7. Un fichier HTML déguisé en photo est refusé.
8. Une inscription sans vérification de l'e-mail est refusée.
"""


import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from applications.commandes.models import Commande, LigneCommande, StatutCommande
from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement
from applications.livraisons.models import DisponibiliteLivreur, ProfilLivreur
from applications.livraisons.services import accepter_mission_livraison, demarrer_trajet_vers_client, pointer_article_au_guichet
from applications.paiements.models import TentativePaiement
from applications.utilisateurs.models import DocumentJustificatif, Role, TypeDocument, Utilisateur


def creer_utilisateur(courriel, telephone, role):
    return Utilisateur.objects.create_user(
        courriel=courriel, password="Password123!", prenom="Test", nom="Ayyou", telephone=telephone, role=role
    )


def creer_livreur(courriel, telephone, valide=True):
    utilisateur = creer_utilisateur(courriel, telephone, Role.LIVREUR)
    statut = StatutValidationPartenaire.ACTIF if valide else StatutValidationPartenaire.EN_ATTENTE_VALIDATION
    disponibilite = DisponibiliteLivreur.EN_LIGNE if valide else DisponibiliteLivreur.HORS_LIGNE
    return ProfilLivreur.objects.create(utilisateur=utilisateur, statut_validation=statut, disponibilite=disponibilite)


def client_api(utilisateur=None):
    api = APIClient()
    if utilisateur:
        api.force_authenticate(utilisateur)
    return api


@pytest.fixture
def commande_prete(db):
    client = creer_utilisateur("client.secu@ayyou.sn", "+221770000101", Role.CLIENT)
    gerant = creer_utilisateur("gerant.secu@ayyou.sn", "+221770000102", Role.RESTAURANT)
    etablissement = Etablissement.objects.create(
        gerant=gerant, nom="Chez Secu", nom_utilisateur="chez-secu",
        statut_validation=StatutValidationPartenaire.ACTIF, est_ouvert=True,
    )
    commande = Commande.objects.create(
        client=client, etablissement=etablissement, statut=StatutCommande.PRETE_POUR_RETRAIT,
        adresse_livraison="Sacré-Cœur 3, villa 42", telephone_contact="+221770000101",
        sous_total_fcfa=3000, frais_livraison_fcfa=1000, total_fcfa=4000,
    )
    LigneCommande.objects.create(commande=commande, nom_plat="Thieb", prix_unitaire_fcfa=3000, quantite=1)
    return commande


@pytest.mark.django_db
class TestSecuriteLivreur:
    def test_livreur_ne_peut_pas_terminer_la_commande_d_un_autre(self, commande_prete):
        livreur_a = creer_livreur("a@ayyou.sn", "+221770000201")
        livreur_b = creer_livreur("b@ayyou.sn", "+221770000202")
        livraison = accepter_mission_livraison(commande_prete, livreur_b)
        pointer_article_au_guichet(livraison, commande_prete.lignes.first().id, True)
        demarrer_trajet_vers_client(livraison)

        reponse = client_api(livreur_a.utilisateur).post(
            f"/api/commandes/{commande_prete.id}/valider-pin/",
            {"code_pin": commande_prete.code_livraison_pin}, format="json",
        )
        assert reponse.status_code == 403
        commande_prete.refresh_from_db()
        assert commande_prete.statut == StatutCommande.EN_LIVRAISON

        # Par l'endpoint « mission en cours », le livreur A n'a tout simplement aucune livraison.
        reponse = client_api(livreur_a.utilisateur).post(
            "/api/livraisons/mission-en-cours/valider-pin/", {"code_pin": commande_prete.code_livraison_pin}, format="json"
        )
        assert reponse.status_code == 400
        assert reponse.data["code"] == "aucune_livraison"

    def test_livreur_non_valide_ne_recoit_aucune_course(self, commande_prete):
        livreur = creer_livreur("nonvalide@ayyou.sn", "+221770000203", valide=False)
        api = client_api(livreur.utilisateur)

        assert api.get("/api/livraisons/propositions/").data == []
        reponse = api.patch("/api/livraisons/disponibilite/", {"disponibilite": "EN_LIGNE"}, format="json")
        assert reponse.status_code == 403
        reponse = api.post(f"/api/livraisons/{commande_prete.id}/accepter/")
        assert reponse.status_code == 403

    def test_livreur_occupe_ne_peut_pas_accepter_une_seconde_course(self, commande_prete):
        livreur = creer_livreur("occupe@ayyou.sn", "+221770000204")
        accepter_mission_livraison(commande_prete, livreur)
        seconde = Commande.objects.create(
            client=commande_prete.client, etablissement=commande_prete.etablissement,
            statut=StatutCommande.PRETE_POUR_RETRAIT, adresse_livraison="Ouakam", telephone_contact="+221770000101",
            sous_total_fcfa=1000, frais_livraison_fcfa=500, total_fcfa=1500,
        )
        reponse = client_api(livreur.utilisateur).post(f"/api/livraisons/{seconde.id}/accepter/")
        assert reponse.status_code == 400

    def test_proposition_ne_revele_pas_le_client(self, commande_prete):
        livreur = creer_livreur("prop@ayyou.sn", "+221770000205")
        propositions = client_api(livreur.utilisateur).get("/api/livraisons/propositions/").data
        assert len(propositions) == 1
        texte = str(propositions[0])
        assert "+221770000101" not in texte
        assert "Sacré-Cœur" not in texte


@pytest.mark.django_db
class TestSecuriteDocuments:
    def test_document_lisible_uniquement_par_proprietaire_ou_admin(self, tmp_path, settings):
        settings.MEDIA_ROOT = tmp_path
        proprietaire = creer_utilisateur("proprio@ayyou.sn", "+221770000301", Role.LIVREUR)
        intrus = creer_utilisateur("intrus@ayyou.sn", "+221770000302", Role.LIVREUR)
        admin = creer_utilisateur("admin.secu@ayyou.sn", "+221770000303", Role.ADMINISTRATEUR)
        document = DocumentJustificatif.objects.create(
            proprietaire=proprietaire, type_document=TypeDocument.CNI,
            fichier=SimpleUploadedFile("cni.pdf", b"%PDF-1.4 contenu", content_type="application/pdf"),
        )
        url = f"/api/utilisateurs/documents/{document.id}/fichier/"

        assert client_api(intrus).get(url).status_code == 404
        assert client_api().get(url).status_code == 401
        assert client_api(proprietaire).get(url).status_code == 200
        assert client_api(admin).get(url).status_code == 200

        # L'URL publique /medias/ refuse toujours les pièces justificatives.
        assert client_api().get(f"/medias/{document.fichier.name}").status_code == 404
        assert client_api().get("/medias/photos/../" + document.fichier.name).status_code == 404

    def test_medias_refuse_les_fichiers_dangereux(self, tmp_path, settings):
        settings.MEDIA_ROOT = tmp_path
        (tmp_path / "piege.html").write_text("<script>alert(1)</script>")
        assert client_api().get("/medias/piege.html").status_code == 404

    def test_photo_html_deguisee_refusee(self, db):
        utilisateur = creer_utilisateur("photo@ayyou.sn", "+221770000304", Role.CLIENT)
        faux = SimpleUploadedFile("photo.jpg", b"<html><script>alert(1)</script></html>", content_type="image/jpeg")
        reponse = client_api(utilisateur).patch("/api/utilisateurs/moi/", {"photo": faux}, format="multipart")
        assert reponse.status_code == 400

        html = SimpleUploadedFile("photo.html", b"<html></html>", content_type="text/html")
        reponse = client_api(utilisateur).patch("/api/utilisateurs/moi/", {"photo": html}, format="multipart")
        assert reponse.status_code == 400


@pytest.mark.django_db
class TestSecuritePaiement:
    def test_fausse_notification_sans_cles_refusee(self, commande_prete, settings):
        settings.PAYTECH_CLE_API = ""
        settings.PAYTECH_CLE_SECRETE = ""
        commande_prete.statut = StatutCommande.EN_ATTENTE_PAIEMENT
        commande_prete.save()
        tentative = TentativePaiement.objects.create(commande=commande_prete, montant_fcfa=commande_prete.total_fcfa)

        reponse = client_api().post(
            "/api/paiements/webhook-ipn/",
            {"ref_command": tentative.reference_paiement, "type_event": "sale_complete", "item_price": 4000},
            format="json",
        )
        assert reponse.status_code == 400
        commande_prete.refresh_from_db()
        assert commande_prete.statut == StatutCommande.EN_ATTENTE_PAIEMENT

    def test_fausse_notification_sans_signature_refusee(self, commande_prete, settings):
        settings.PAYTECH_CLE_API = "cle_api"
        settings.PAYTECH_CLE_SECRETE = "cle_secrete"
        commande_prete.statut = StatutCommande.EN_ATTENTE_PAIEMENT
        commande_prete.save()
        tentative = TentativePaiement.objects.create(commande=commande_prete, montant_fcfa=commande_prete.total_fcfa)

        reponse = client_api().post(
            "/api/paiements/webhook-ipn/",
            {"ref_command": tentative.reference_paiement, "type_event": "sale_complete", "item_price": 4000},
            format="json",
        )
        assert reponse.status_code == 400


@pytest.mark.django_db
def test_inscription_sans_verification_email_refusee():
    reponse = client_api().post(
        "/api/authentification/inscription/",
        {
            "prenom": "Awa", "nom": "Ndiaye", "courriel": "awa@ayyou.sn", "telephone": "771234567",
            "mot_de_passe": "MotDePasse!Solide9", "confirmation_mot_de_passe": "MotDePasse!Solide9",
            "role": "CLIENT", "conditions_acceptees": True,
        },
        format="json",
    )
    assert reponse.status_code == 400
    assert "courriel" in reponse.data
