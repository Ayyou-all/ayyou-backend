"""
Test de la phase 11 : GPS réel du livreur, transmis au client qui suit sa commande.
"""

import pytest
from rest_framework.test import APIClient

from applications.commandes.models import Commande, StatutCommande
from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement
from applications.livraisons.models import DisponibiliteLivreur, Livraison, ProfilLivreur
from applications.utilisateurs.models import Role, Utilisateur


def creer(courriel, telephone, role):
    return Utilisateur.objects.create_user(
        courriel=courriel, password="Password123!", prenom="G", nom="Ps", telephone=telephone, role=role
    )


@pytest.mark.django_db
def test_position_gps_du_livreur_visible_par_son_client():
    client = creer("c11@ayyou.sn", "+221770011001", Role.CLIENT)
    autre_client = creer("c11b@ayyou.sn", "+221770011002", Role.CLIENT)
    gerant = creer("g11@ayyou.sn", "+221770011003", Role.RESTAURANT)
    livreur = ProfilLivreur.objects.create(
        utilisateur=creer("l11@ayyou.sn", "+221770011004", Role.LIVREUR),
        statut_validation=StatutValidationPartenaire.ACTIF, disponibilite=DisponibiliteLivreur.OCCUPE,
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant, nom="R11", nom_utilisateur="r11", statut_validation=StatutValidationPartenaire.ACTIF
    )
    commande = Commande.objects.create(
        client=client, etablissement=etablissement, statut=StatutCommande.EN_LIVRAISON, adresse_livraison="Fann",
        telephone_contact="+221770011001", sous_total_fcfa=2000, frais_livraison_fcfa=1000, total_fcfa=3000,
    )
    Livraison.objects.create(commande=commande, livreur=livreur)

    api_livreur = APIClient()
    api_livreur.force_authenticate(livreur.utilisateur)
    assert api_livreur.patch("/api/livraisons/position-gps/", {"latitude": "14.6937", "longitude": "-17.4441"}, format="json").status_code == 200

    # Un client ne peut pas envoyer de position de livreur
    api_client = APIClient()
    api_client.force_authenticate(client)
    assert api_client.patch("/api/livraisons/position-gps/", {"latitude": "1", "longitude": "1"}, format="json").status_code == 403

    # Le client voit la vraie position de SON livreur
    suivi = api_client.get(f"/api/commandes/{commande.id}/").data
    assert suivi["livreur"]["latitude"] == pytest.approx(14.6937)
    assert suivi["livreur"]["longitude"] == pytest.approx(-17.4441)

    # Un autre client ne peut pas suivre cette commande
    api_autre = APIClient()
    api_autre.force_authenticate(autre_client)
    assert api_autre.get(f"/api/commandes/{commande.id}/").status_code in (403, 404)
