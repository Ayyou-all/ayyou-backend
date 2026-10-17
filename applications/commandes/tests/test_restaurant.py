"""
Tests de la phase 4 (restaurant) : remise au livreur et tableau de cuisine du jour.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from applications.commandes.models import Commande, LigneCommande, StatutCommande
from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import ErreurMetier
from applications.etablissements.models import Etablissement
from applications.livraisons.models import DisponibiliteLivreur, ProfilLivreur
from applications.livraisons.services import accepter_mission_livraison, demarrer_trajet_vers_client, pointer_article_au_guichet
from applications.utilisateurs.models import Role, Utilisateur


def creer(courriel, telephone, role):
    return Utilisateur.objects.create_user(
        courriel=courriel, password="Password123!", prenom="Test", nom="Resto", telephone=telephone, role=role
    )


@pytest.fixture
def cuisine(db):
    client = creer("c4@ayyou.sn", "+221770004001", Role.CLIENT)
    gerant = creer("g4@ayyou.sn", "+221770004002", Role.RESTAURANT)
    autre_gerant = creer("g4b@ayyou.sn", "+221770004003", Role.RESTAURANT)
    livreur = ProfilLivreur.objects.create(
        utilisateur=creer("l4@ayyou.sn", "+221770004004", Role.LIVREUR),
        statut_validation=StatutValidationPartenaire.ACTIF, disponibilite=DisponibiliteLivreur.EN_LIGNE,
        latitude=14.6928, longitude=-17.4467, date_derniere_position=timezone.now(),
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant, nom="Resto 4", nom_utilisateur="resto-4", statut_validation=StatutValidationPartenaire.ACTIF, est_ouvert=True
    )
    Etablissement.objects.create(gerant=autre_gerant, nom="Autre", nom_utilisateur="autre-4", statut_validation=StatutValidationPartenaire.ACTIF)
    commande = Commande.objects.create(
        client=client, etablissement=etablissement, statut=StatutCommande.PRETE_POUR_RETRAIT,
        adresse_livraison="HLM", telephone_contact="+221770004001", sous_total_fcfa=2000, frais_livraison_fcfa=1000, total_fcfa=3000,
    )
    LigneCommande.objects.create(commande=commande, nom_plat="Mafé", prix_unitaire_fcfa=2000, quantite=1)
    return {"gerant": gerant, "autre_gerant": autre_gerant, "livreur": livreur, "commande": commande}


def api(utilisateur):
    client = APIClient()
    client.force_authenticate(utilisateur)
    return client


@pytest.mark.django_db
def test_remise_impossible_sans_livreur(cuisine):
    reponse = api(cuisine["gerant"]).post(f"/api/commandes/{cuisine['commande'].id}/remettre-au-livreur/")
    assert reponse.status_code == 400
    assert reponse.data["code"] == "aucun_livreur"


@pytest.mark.django_db
def test_livreur_ne_part_pas_sans_confirmation_de_remise(cuisine):
    livraison = accepter_mission_livraison(cuisine["commande"], cuisine["livreur"])
    pointer_article_au_guichet(livraison, cuisine["commande"].lignes.first().id, True)
    with pytest.raises(ErreurMetier) as erreur:
        demarrer_trajet_vers_client(livraison)
    assert erreur.value.code == "remise_non_confirmee"

    # Un autre restaurant ne peut pas confirmer la remise.
    reponse = api(cuisine["autre_gerant"]).post(f"/api/commandes/{cuisine['commande'].id}/remettre-au-livreur/")
    assert reponse.status_code == 403

    reponse = api(cuisine["gerant"]).post(f"/api/commandes/{cuisine['commande'].id}/remettre-au-livreur/")
    assert reponse.status_code == 200
    assert reponse.data["remise_confirmee"] is True
    demarrer_trajet_vers_client(livraison)
    cuisine["commande"].refresh_from_db()
    assert cuisine["commande"].statut == StatutCommande.EN_LIVRAISON


@pytest.mark.django_db
def test_tableau_du_jour_ne_renvoie_pas_les_vieilles_commandes_terminees(cuisine):
    vieille = Commande.objects.create(
        client=cuisine["commande"].client, etablissement=cuisine["commande"].etablissement, statut=StatutCommande.LIVREE,
        adresse_livraison="HLM", telephone_contact="+221770004001", sous_total_fcfa=1000, frais_livraison_fcfa=500, total_fcfa=1500,
    )
    Commande.objects.filter(pk=vieille.pk).update(date_creation=timezone.now() - timedelta(days=3))

    references = [c["reference"] for c in api(cuisine["gerant"]).get("/api/commandes/restaurant/?vue=jour").data]
    assert cuisine["commande"].reference in references
    assert vieille.reference not in references
