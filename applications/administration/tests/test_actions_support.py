"""
Tests de la phase 6 : actions du support sur les commandes et liste admin filtrée par le serveur.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from applications.commandes.models import Commande, HistoriqueStatutCommande, LigneCommande, StatutCommande
from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement
from applications.livraisons.models import DisponibiliteLivreur, ProfilLivreur
from applications.paiements.models import StatutPaiement, TentativePaiement
from applications.utilisateurs.models import Role, Utilisateur


def creer(courriel, telephone, role, prenom="Test"):
    return Utilisateur.objects.create_user(
        courriel=courriel, password="Password123!", prenom=prenom, nom="Support", telephone=telephone, role=role
    )


@pytest.fixture
def support(db, settings, monkeypatch):
    settings.PAYTECH_CLE_API = "cle"
    settings.PAYTECH_CLE_SECRETE = "secret"
    remboursements = []

    class Reponse:
        status_code = 200

        def json(self):
            return {"success": 1}

    def faux_post(url, *args, **kwargs):
        remboursements.append(kwargs["data"]["ref_command"])
        return Reponse()

    monkeypatch.setattr("requests.post", faux_post)

    admin = creer("adm6@ayyou.sn", "+221770006001", Role.ADMINISTRATEUR)
    client = creer("cli6@ayyou.sn", "+221770006002", Role.CLIENT, prenom="Mariama")
    gerant = creer("ger6@ayyou.sn", "+221770006003", Role.RESTAURANT)
    livreur = ProfilLivreur.objects.create(
        utilisateur=creer("liv6@ayyou.sn", "+221770006004", Role.LIVREUR),
        statut_validation=StatutValidationPartenaire.ACTIF, disponibilite=DisponibiliteLivreur.EN_LIGNE,
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant, nom="Resto 6", nom_utilisateur="resto-6", statut_validation=StatutValidationPartenaire.ACTIF
    )
    api = APIClient()
    api.force_authenticate(admin)
    return {"api": api, "admin": admin, "client": client, "livreur": livreur, "etablissement": etablissement, "remboursements": remboursements}


def commande(support, statut, paye=True):
    c = Commande.objects.create(
        client=support["client"], etablissement=support["etablissement"], statut=statut,
        adresse_livraison="Ouakam", telephone_contact="+221770006002",
        sous_total_fcfa=3000, frais_livraison_fcfa=1000, total_fcfa=4000, heure_fin_preparation=timezone.now(),
    )
    LigneCommande.objects.create(commande=c, nom_plat="Thiou", prix_unitaire_fcfa=3000, quantite=1)
    if paye:
        TentativePaiement.objects.create(commande=c, montant_fcfa=4000, statut=StatutPaiement.CONFIRME)
    return c


@pytest.mark.django_db
def test_admin_annule_et_rembourse(support):
    c = commande(support, StatutCommande.EN_PREPARATION)
    reponse = support["api"].post(f"/api/administration/commandes/{c.id}/annuler/", {"motif": "Client injoignable"}, format="json")
    assert reponse.status_code == 200
    assert reponse.data["statutDetaille"] == "REFUSEE_ANNULEE"
    assert reponse.data["paiementARembourser"] is False
    assert len(support["remboursements"]) == 1
    assert HistoriqueStatutCommande.objects.filter(commande=c, auteur=support["admin"]).exists()


@pytest.mark.django_db
def test_admin_ne_peut_pas_annuler_une_commande_en_route(support):
    c = commande(support, StatutCommande.EN_LIVRAISON)
    reponse = support["api"].post(f"/api/administration/commandes/{c.id}/annuler/", {"motif": "x"}, format="json")
    assert reponse.status_code == 400
    assert reponse.data["code"] == "commande_en_route"


@pytest.mark.django_db
def test_remboursement_d_un_echec_de_livraison(support):
    c = commande(support, StatutCommande.ECHEC_LIVRAISON)
    liste = support["api"].get("/api/administration/commandes/?statut=A_REMBOURSER").data
    assert [r["id"] for r in liste["results"]] == [c.id]

    reponse = support["api"].post(f"/api/administration/commandes/{c.id}/rembourser/")
    assert reponse.status_code == 200
    assert reponse.data["paiementARembourser"] is False
    # Rien à rembourser une seconde fois
    assert support["api"].post(f"/api/administration/commandes/{c.id}/rembourser/").status_code == 400


@pytest.mark.django_db
def test_assignation_manuelle_puis_retrait_du_livreur(support):
    c = commande(support, StatutCommande.PRETE_POUR_RETRAIT)
    livreur = support["livreur"]  # sans GPS : l'assignation manuelle reste possible
    reponse = support["api"].post(
        f"/api/administration/commandes/{c.id}/assigner-livreur/", {"livreur_id": livreur.id}, format="json"
    )
    assert reponse.status_code == 200
    assert reponse.data["statutDetaille"] == "COURSE_ASSIGNEE"

    reponse = support["api"].post(f"/api/administration/commandes/{c.id}/retirer-livreur/", {"motif": "Trop lent"}, format="json")
    assert reponse.status_code == 200
    assert reponse.data["statutDetaille"] == "PRETE_POUR_RETRAIT"
    livreur.refresh_from_db()
    assert livreur.disponibilite == DisponibiliteLivreur.EN_LIGNE


@pytest.mark.django_db
def test_liste_paginee_et_recherche_serveur(support):
    for _ in range(25):
        commande(support, StatutCommande.LIVREE, paye=False)
    page = support["api"].get("/api/administration/commandes/?statut=LIVREES").data
    assert page["count"] == 25
    assert len(page["results"]) == 20
    assert support["api"].get("/api/administration/commandes/?recherche=Mariama").data["count"] == 25
    assert support["api"].get("/api/administration/commandes/?recherche=Inconnu").data["count"] == 0


@pytest.mark.django_db
def test_desactiver_un_livreur_le_met_hors_ligne(support):
    livreur = support["livreur"]
    reponse = support["api"].post(
        f"/api/administration/utilisateurs/{livreur.utilisateur.id}/basculer-statut/", {"action": "desactiver"}, format="json"
    )
    assert reponse.status_code == 200
    livreur.refresh_from_db()
    assert livreur.disponibilite == DisponibiliteLivreur.HORS_LIGNE
    # Un administrateur ne peut pas se désactiver lui-même
    soi = support["api"].post(f"/api/administration/utilisateurs/{support['admin'].id}/basculer-statut/", {}, format="json")
    assert soi.status_code == 400


@pytest.mark.django_db
def test_debloquer_une_livraison_apres_5_pin_errones(support):
    from applications.livraisons.models import Livraison

    c = commande(support, StatutCommande.ARRIVE_CLIENT)
    livraison = Livraison.objects.create(commande=c, livreur=support["livreur"], essais_code_echoues=5)
    detail = support["api"].get("/api/administration/commandes/?statut=EN_COURS").data["results"][0]
    assert detail["livraisonBloquee"] is True

    reponse = support["api"].post(f"/api/administration/commandes/{c.id}/debloquer/")
    assert reponse.status_code == 200
    assert reponse.data["livraisonBloquee"] is False
    livraison.refresh_from_db()
    assert livraison.essais_code_echoues == 0
    # Une livraison non bloquée ne peut pas être « débloquée »
    assert support["api"].post(f"/api/administration/commandes/{c.id}/debloquer/").status_code == 400
