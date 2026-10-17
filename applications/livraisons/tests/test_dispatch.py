"""
Tests de la phase 5 : dispatch par distance, refus, annulation et échec de livraison.

Positions utilisées (Dakar) :
- restaurant au Plateau      : 14.6700, -17.4300
- livreur proche (Médina)    : 14.6850, -17.4450  (~2,3 km)
- livreur loin (Parcelles)   : 14.7700, -17.4400  (~11 km)
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from applications.commandes.models import Commande, LigneCommande, StatutCommande
from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import ErreurMetier
from applications.etablissements.models import Etablissement
from applications.livraisons.models import DisponibiliteLivreur, EtapeLivraison, ProfilLivreur
from applications.livraisons.services import (
    accepter_mission_livraison,
    annuler_course_par_livreur,
    declarer_echec_livraison,
    demarrer_trajet_vers_client,
    lister_courses_disponibles,
    pointer_article_au_guichet,
    refuser_course,
)
from applications.utilisateurs.models import Role, Utilisateur

PLATEAU = (14.6700, -17.4300)
MEDINA = (14.6850, -17.4450)
PARCELLES = (14.7700, -17.4400)


def creer_livreur(courriel, telephone, position, date_position=None):
    utilisateur = Utilisateur.objects.create_user(
        courriel=courriel, password="Password123!", prenom="Liv", nom="Reur", telephone=telephone, role=Role.LIVREUR
    )
    return ProfilLivreur.objects.create(
        utilisateur=utilisateur,
        statut_validation=StatutValidationPartenaire.ACTIF,
        disponibilite=DisponibiliteLivreur.EN_LIGNE,
        latitude=position[0] if position else None,
        longitude=position[1] if position else None,
        date_derniere_position=date_position or (timezone.now() if position else None),
    )


@pytest.fixture
def commande_prete(db):
    client = Utilisateur.objects.create_user(
        courriel="c5@ayyou.sn", password="Password123!", prenom="Cli", nom="Ent", telephone="+221770005001", role=Role.CLIENT
    )
    gerant = Utilisateur.objects.create_user(
        courriel="g5@ayyou.sn", password="Password123!", prenom="Ge", nom="Rant", telephone="+221770005002", role=Role.RESTAURANT
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant, nom="Plateau Grill", nom_utilisateur="plateau-grill",
        statut_validation=StatutValidationPartenaire.ACTIF, est_ouvert=True, latitude=PLATEAU[0], longitude=PLATEAU[1],
    )
    commande = Commande.objects.create(
        client=client, etablissement=etablissement, statut=StatutCommande.PRETE_POUR_RETRAIT,
        adresse_livraison="Point E", telephone_contact="+221770005001", latitude_livraison=14.69, longitude_livraison=-17.46,
        sous_total_fcfa=3000, frais_livraison_fcfa=1500, total_fcfa=4500, heure_fin_preparation=timezone.now(),
    )
    LigneCommande.objects.create(commande=commande, nom_plat="Dibi", prix_unitaire_fcfa=3000, quantite=1)
    return commande


@pytest.mark.django_db
def test_seul_le_livreur_proche_voit_la_course(commande_prete):
    proche = creer_livreur("p@ayyou.sn", "+221770005101", MEDINA)
    loin = creer_livreur("l@ayyou.sn", "+221770005102", PARCELLES)
    assert lister_courses_disponibles(proche) == [commande_prete]
    assert lister_courses_disponibles(loin) == []


@pytest.mark.django_db
def test_rayon_elargi_quand_personne_n_accepte(commande_prete):
    loin = creer_livreur("l2@ayyou.sn", "+221770005103", PARCELLES)
    # Prête depuis 20 minutes : le rayon a atteint le maximum (15 km)
    Commande.objects.filter(pk=commande_prete.pk).update(heure_fin_preparation=timezone.now() - timedelta(minutes=20))
    assert lister_courses_disponibles(loin) == [commande_prete]


@pytest.mark.django_db
def test_livreur_sans_gps_ou_gps_ancien_ne_recoit_rien(commande_prete):
    sans_gps = creer_livreur("s@ayyou.sn", "+221770005104", None)
    gps_ancien = creer_livreur("a@ayyou.sn", "+221770005105", MEDINA, timezone.now() - timedelta(minutes=30))
    assert lister_courses_disponibles(sans_gps) == []
    assert lister_courses_disponibles(gps_ancien) == []


@pytest.mark.django_db
def test_acceptation_refusee_hors_rayon(commande_prete):
    loin = creer_livreur("l3@ayyou.sn", "+221770005106", PARCELLES)
    with pytest.raises(ErreurMetier) as erreur:
        accepter_mission_livraison(commande_prete, loin)
    assert erreur.value.code == "course_non_proposee"


@pytest.mark.django_db
def test_course_refusee_n_est_plus_proposee_a_ce_livreur(commande_prete):
    premier = creer_livreur("r1@ayyou.sn", "+221770005107", MEDINA)
    second = creer_livreur("r2@ayyou.sn", "+221770005108", MEDINA)
    refuser_course(premier, commande_prete)
    assert lister_courses_disponibles(premier) == []
    assert lister_courses_disponibles(second) == [commande_prete]


@pytest.mark.django_db
def test_annulation_avant_recuperation_repropose_la_course(commande_prete):
    premier = creer_livreur("x1@ayyou.sn", "+221770005109", MEDINA)
    second = creer_livreur("x2@ayyou.sn", "+221770005110", MEDINA)
    accepter_mission_livraison(commande_prete, premier)

    annuler_course_par_livreur(premier, "Crevaison")
    commande_prete.refresh_from_db()
    premier.refresh_from_db()
    assert commande_prete.statut == StatutCommande.PRETE_POUR_RETRAIT
    assert premier.disponibilite == DisponibiliteLivreur.EN_LIGNE
    assert lister_courses_disponibles(premier) == []
    assert lister_courses_disponibles(second) == [commande_prete]
    accepter_mission_livraison(commande_prete, second)  # un nouveau livreur peut l'accepter


@pytest.mark.django_db
def test_annulation_impossible_apres_remise(commande_prete):
    livreur = creer_livreur("y@ayyou.sn", "+221770005111", MEDINA)
    livraison = accepter_mission_livraison(commande_prete, livreur)
    livraison.date_remise_restaurant = timezone.now()
    livraison.save()
    with pytest.raises(ErreurMetier) as erreur:
        annuler_course_par_livreur(livreur, "Je ne veux plus")
    assert erreur.value.code == "annulation_impossible"


@pytest.mark.django_db
def test_echec_de_livraison_client_absent(commande_prete):
    livreur = creer_livreur("z@ayyou.sn", "+221770005112", MEDINA)
    livraison = accepter_mission_livraison(commande_prete, livreur)
    livraison.date_remise_restaurant = timezone.now()
    livraison.save()
    pointer_article_au_guichet(livraison, commande_prete.lignes.first().id, True)
    demarrer_trajet_vers_client(livraison)

    declarer_echec_livraison(livreur, "CLIENT_ABSENT")
    commande_prete.refresh_from_db()
    livraison.refresh_from_db()
    livreur.refresh_from_db()
    assert commande_prete.statut == StatutCommande.ECHEC_LIVRAISON
    assert commande_prete.motif_refus_ou_annulation == "Client absent"
    assert livraison.etape == EtapeLivraison.ECHOUEE
    assert livreur.disponibilite == DisponibiliteLivreur.EN_LIGNE


@pytest.mark.django_db
def test_echec_impossible_avant_depart(commande_prete):
    livreur = creer_livreur("w@ayyou.sn", "+221770005113", MEDINA)
    accepter_mission_livraison(commande_prete, livreur)
    with pytest.raises(ErreurMetier):
        declarer_echec_livraison(livreur, "CLIENT_ABSENT")
