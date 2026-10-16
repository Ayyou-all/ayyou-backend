"""
Tests automatisés pour le domaine Livraison et espace Coursier.

Scénarios testés :
1. Consultation des courses disponibles par un livreur actif.
2. Acceptation de course : assignation et passage en statut OCCUPE.
3. Pointage des articles au comptoir.
4. Blocage du départ si des articles ne sont pas pointés.
5. Remise finale avec validation du PIN client et libération du coursier.
"""

import pytest

from applications.commandes.models import Commande, LigneCommande, StatutCommande
from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import ErreurMetier
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.livraisons.models import DisponibiliteLivreur, EtapeLivraison, ProfilLivreur, TypeVehicule
from applications.livraisons.services import (
    accepter_mission_livraison,
    demarrer_trajet_vers_client,
    lister_courses_disponibles,
    pointer_article_au_guichet,
    valider_livraison_avec_pin,
)
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def environnement_livraison(db):
    client = Utilisateur.objects.create_user(
        courriel="client.liv@ayyou.sn",
        password="Password123!",
        prenom="Ndeye",
        nom="Diouf",
        telephone="+221773334455",
        role=Role.CLIENT,
    )
    gerant = Utilisateur.objects.create_user(
        courriel="gerant.liv@ayyou.sn",
        password="Password123!",
        prenom="Babacar",
        nom="Sene",
        telephone="+221775556677",
        role=Role.RESTAURANT,
    )
    livreur_user = Utilisateur.objects.create_user(
        courriel="coursier@ayyou.sn",
        password="Password123!",
        prenom="Modou",
        nom="Gueye",
        telephone="+221779998877",
        role=Role.LIVREUR,
    )
    profil_livreur = ProfilLivreur.objects.create(
        utilisateur=livreur_user,
        type_vehicule=TypeVehicule.MOTO,
        nom_vehicule="Kymco Agility 125",
        statut_validation=StatutValidationPartenaire.ACTIF,
        disponibilite=DisponibiliteLivreur.EN_LIGNE,
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant,
        type_etablissement=TypeEtablissement.RESTAURANT,
        nom="Le Djembe",
        nom_utilisateur="le-djembe",
        statut_validation=StatutValidationPartenaire.ACTIF,
        est_ouvert=True,
        frais_livraison_fcfa=1500,
    )
    commande = Commande.objects.create(
        client=client,
        etablissement=etablissement,
        statut=StatutCommande.PRETE_POUR_RETRAIT,
        adresse_livraison="Grand Yoff, Dakar",
        telephone_contact="+221773334455",
        sous_total_fcfa=4000,
        frais_livraison_fcfa=1500,
        total_fcfa=5500,
    )
    art1 = LigneCommande.objects.create(
        commande=commande,
        nom_plat="Dibi d'agneau",
        prix_unitaire_fcfa=3000,
        quantite=1,
    )
    art2 = LigneCommande.objects.create(
        commande=commande,
        nom_plat="Jus de Bissap 50cl",
        prix_unitaire_fcfa=1000,
        quantite=1,
    )
    return {
        "profil_livreur": profil_livreur,
        "commande": commande,
        "art1": art1,
        "art2": art2,
    }


@pytest.mark.django_db
class TestLivraisons:
    def test_liste_courses_disponibles(self, environnement_livraison):
        profil = environnement_livraison["profil_livreur"]
        courses = lister_courses_disponibles(profil)

        assert courses.count() == 1
        assert courses.first().id == environnement_livraison["commande"].id

    def test_acceptation_mission_coursier(self, environnement_livraison):
        profil = environnement_livraison["profil_livreur"]
        commande = environnement_livraison["commande"]

        livraison = accepter_mission_livraison(commande, profil)

        assert livraison.livreur == profil
        assert livraison.etape == EtapeLivraison.VERS_RESTAURANT
        assert livraison.gain_livreur_fcfa >= 1000

        commande.refresh_from_db()
        assert commande.statut == StatutCommande.COURSE_ASSIGNEE

        profil.refresh_from_db()
        assert profil.disponibilite == DisponibiliteLivreur.OCCUPE

    def test_commande_non_acceptee_non_proposee_au_livreur(self, environnement_livraison):
        profil = environnement_livraison["profil_livreur"]
        commande = environnement_livraison["commande"]
        # Passer la commande en attente d'acceptation par le restaurant
        commande.statut = StatutCommande.CREEE_EN_ATTENTE
        commande.save(update_fields=["statut"])

        courses = lister_courses_disponibles(profil)
        assert courses.filter(id=commande.id).exists() is False

    def test_double_acceptation_concurrente_rejetee(self, environnement_livraison):
        profil1 = environnement_livraison["profil_livreur"]
        commande = environnement_livraison["commande"]

        autre_user = Utilisateur.objects.create_user(
            courriel="autre.coursier@ayyou.sn",
            password="Password123!",
            prenom="Alioune",
            nom="Fall",
            telephone="+221771112233",
            role=Role.LIVREUR,
        )
        profil2 = ProfilLivreur.objects.create(
            utilisateur=autre_user,
            type_vehicule=TypeVehicule.SCOOTER,
            statut_validation=StatutValidationPartenaire.ACTIF,
            disponibilite=DisponibiliteLivreur.EN_LIGNE,
        )

        accepter_mission_livraison(commande, profil1)

        with pytest.raises(ErreurMetier) as exc:
            accepter_mission_livraison(commande, profil2)
        assert exc.value.code in {"course_deja_assignee", "course_indisponible"}

    def test_pointage_articles_et_depart_client(self, environnement_livraison):
        profil = environnement_livraison["profil_livreur"]
        commande = environnement_livraison["commande"]
        art1 = environnement_livraison["art1"]
        art2 = environnement_livraison["art2"]

        livraison = accepter_mission_livraison(commande, profil)

        # Pointer seulement 1 article sur 2
        pointer_article_au_guichet(livraison, art1.id, est_verifie=True)

        commande.refresh_from_db()
        assert commande.statut == StatutCommande.EN_VERIFICATION

        # Tenter de partir sans cocher le second article : refus obligatoire
        with pytest.raises(ErreurMetier) as exc:
            demarrer_trajet_vers_client(livraison)
        assert "vérifier l'ensemble des articles" in str(exc.value)

        # Pointer le 2ème article et partir
        pointer_article_au_guichet(livraison, art2.id, est_verifie=True)
        demarrer_trajet_vers_client(livraison)

        commande.refresh_from_db()
        assert commande.statut == StatutCommande.EN_LIVRAISON
        assert livraison.etape == EtapeLivraison.VERS_CLIENT

    def test_validation_pin_et_liberation_livreur(self, environnement_livraison):
        profil = environnement_livraison["profil_livreur"]
        commande = environnement_livraison["commande"]
        art1 = environnement_livraison["art1"]
        art2 = environnement_livraison["art2"]

        livraison = accepter_mission_livraison(commande, profil)
        pointer_article_au_guichet(livraison, art1.id, est_verifie=True)
        pointer_article_au_guichet(livraison, art2.id, est_verifie=True)
        demarrer_trajet_vers_client(livraison)

        # Passer en ARRIVE_CLIENT
        commande.statut = StatutCommande.ARRIVE_CLIENT
        commande.save()

        # Validation avec code PIN exact
        valider_livraison_avec_pin(livraison, commande.code_livraison_pin)

        commande.refresh_from_db()
        assert commande.statut == StatutCommande.LIVREE

        livraison.refresh_from_db()
        assert livraison.etape == EtapeLivraison.LIVREE

        # Le coursier doit être libéré et redevenir disponible pour de nouvelles courses
        profil.refresh_from_db()
        assert profil.disponibilite == DisponibiliteLivreur.EN_LIGNE

    def test_refus_acceptation_si_en_preparation(self, environnement_livraison):
        profil = environnement_livraison["profil_livreur"]
        commande = environnement_livraison["commande"]
        # Passer en préparation (cuisine non terminée)
        commande.statut = StatutCommande.EN_PREPARATION
        commande.save(update_fields=["statut"])

        with pytest.raises(ErreurMetier) as exc:
            accepter_mission_livraison(commande, profil)
        assert exc.value.code == "course_indisponible"
        # Le statut ne doit pas avoir bougé (souveraineté restaurant)
        commande.refresh_from_db()
        assert commande.statut == StatutCommande.EN_PREPARATION

    def test_anti_bruteforce_pin_cinq_essais(self, environnement_livraison):
        profil = environnement_livraison["profil_livreur"]
        commande = environnement_livraison["commande"]
        art1 = environnement_livraison["art1"]
        art2 = environnement_livraison["art2"]

        livraison = accepter_mission_livraison(commande, profil)
        pointer_article_au_guichet(livraison, art1.id, est_verifie=True)
        pointer_article_au_guichet(livraison, art2.id, est_verifie=True)
        demarrer_trajet_vers_client(livraison)
        commande.statut = StatutCommande.ARRIVE_CLIENT
        commande.save()

        # 4 tentatives avec un mauvais code PIN
        for _ in range(4):
            with pytest.raises(ErreurMetier) as exc:
                valider_livraison_avec_pin(livraison, "9999")
            assert exc.value.code == "code_pin_invalide"

        # 5ème tentative échouée -> verrouillage immédiat
        with pytest.raises(ErreurMetier) as exc:
            valider_livraison_avec_pin(livraison, "9999")
        assert exc.value.code == "tentatives_depassees"

        # 6ème tentative même avec le bon code PIN -> toujours bloquée
        with pytest.raises(ErreurMetier) as exc:
            valider_livraison_avec_pin(livraison, commande.code_livraison_pin)
        assert exc.value.code == "tentatives_depassees"

    def test_rejet_revalidation_commande_deja_livree(self, environnement_livraison):
        profil = environnement_livraison["profil_livreur"]
        commande = environnement_livraison["commande"]
        art1 = environnement_livraison["art1"]
        art2 = environnement_livraison["art2"]

        livraison = accepter_mission_livraison(commande, profil)
        pointer_article_au_guichet(livraison, art1.id, est_verifie=True)
        pointer_article_au_guichet(livraison, art2.id, est_verifie=True)
        demarrer_trajet_vers_client(livraison)
        commande.statut = StatutCommande.ARRIVE_CLIENT
        commande.save()

        # Première validation réussie
        valider_livraison_avec_pin(livraison, commande.code_livraison_pin)

        # Seconde validation doit être immédiatement rejetée
        with pytest.raises(ErreurMetier) as exc:
            valider_livraison_avec_pin(livraison, commande.code_livraison_pin)
        assert exc.value.code == "commande_deja_livree"
