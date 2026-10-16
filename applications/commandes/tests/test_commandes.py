"""
Tests automatisés pour le domaine Commande.

Scénarios testés :
1. Création d'une commande valide depuis le panier et vérification du total recalculé.
2. Rejet de la commande si un plat du panier devient indisponible.
3. Machine à états : vérification des transitions autorisées et blocage des transitions interdites.
4. Validation du code PIN à 4 chiffres par le livreur (succès et échec).
5. Cloisonnement des permissions inter-rôles.
"""

import pytest

from applications.catalogue.models import CategoriePlat, Plat
from applications.commandes.models import Commande, StatutCommande
from applications.commandes.services import (
    accepter_commande_par_restaurant,
    creer_commande_depuis_panier,
    marquer_commande_prete,
    transitionner_statut_commande,
)
from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import AccesRefuse, ErreurMetier, TransitionInterdite
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.panier.models import LignePanier
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def donnees_test(db):
    # 1. Utilisateurs
    client = Utilisateur.objects.create_user(
        courriel="client@ayyou.sn",
        password="Password123!",
        prenom="Amina",
        nom="Sall",
        telephone="+221770001122",
        role=Role.CLIENT,
    )
    autre_client = Utilisateur.objects.create_user(
        courriel="autre@ayyou.sn",
        password="Password123!",
        prenom="Ibrahima",
        nom="Kane",
        telephone="+221770003344",
        role=Role.CLIENT,
    )
    gerant = Utilisateur.objects.create_user(
        courriel="resto@teranga.sn",
        password="Password123!",
        prenom="Cheikh",
        nom="Ndiaye",
        telephone="+221771112233",
        role=Role.RESTAURANT,
    )
    livreur = Utilisateur.objects.create_user(
        courriel="livreur@ayyou.sn",
        password="Password123!",
        prenom="Moussa",
        nom="Ba",
        telephone="+221772223344",
        role=Role.LIVREUR,
    )

    # 2. Établissement
    etablissement = Etablissement.objects.create(
        gerant=gerant,
        type_etablissement=TypeEtablissement.RESTAURANT,
        nom="Le Teranga Gourmand",
        nom_utilisateur="le-teranga",
        statut_validation=StatutValidationPartenaire.ACTIF,
        est_ouvert=True,
        frais_livraison_fcfa=1000,
    )

    # 3. Plats
    categorie = CategoriePlat.objects.create(nom="Plats sénégalais", slug="plats-senegalais")
    plat1 = Plat.objects.create(
        etablissement=etablissement,
        categorie=categorie,
        nom="Thiéboudienne Penda Mbaye",
        prix_fcfa=3500,
        est_disponible=True,
    )
    plat2 = Plat.objects.create(
        etablissement=etablissement,
        categorie=categorie,
        nom="Yassa Poulet Fermier",
        prix_fcfa=3000,
        est_disponible=True,
    )

    return {
        "client": client,
        "autre_client": autre_client,
        "gerant": gerant,
        "livreur": livreur,
        "etablissement": etablissement,
        "plat1": plat1,
        "plat2": plat2,
    }


@pytest.mark.django_db
class TestCycleDeVieCommande:
    def test_creation_commande_depuis_panier(self, donnees_test):
        client = donnees_test["client"]
        etablissement = donnees_test["etablissement"]
        plat1 = donnees_test["plat1"]
        plat2 = donnees_test["plat2"]

        # Remplir le panier
        LignePanier.objects.create(client=client, plat=plat1, quantite=2)  # 2 * 3500 = 7000
        LignePanier.objects.create(client=client, plat=plat2, quantite=1)  # 1 * 3000 = 3000

        commande = creer_commande_depuis_panier(
            client=client,
            etablissement_id=etablissement.id,
            adresse_livraison="Mermoz, Villa 12, Dakar",
            telephone_contact="+221770001122",
            latitude_livraison=14.6928,
            longitude_livraison=-17.4467,
        )

        assert commande.sous_total_fcfa == 10000
        assert commande.frais_livraison_fcfa == 1000
        assert commande.total_fcfa == 11000
        assert commande.statut == StatutCommande.EN_ATTENTE_PAIEMENT
        assert len(commande.code_livraison_pin) == 4
        assert commande.lignes.count() == 2

        # Vérifier que le sous-panier a bien été vidé
        assert LignePanier.objects.filter(client=client, plat__etablissement=etablissement).count() == 0

    def test_rejet_commande_si_plat_indisponible(self, donnees_test):
        client = donnees_test["client"]
        etablissement = donnees_test["etablissement"]
        plat1 = donnees_test["plat1"]

        plat1.est_disponible = False
        plat1.save()

        LignePanier.objects.create(client=client, plat=plat1, quantite=1)

        with pytest.raises(ErreurMetier) as exc:
            creer_commande_depuis_panier(
                client=client,
                etablissement_id=etablissement.id,
                adresse_livraison="Dakar",
                telephone_contact="+221770001122",
            latitude_livraison=14.6928,
            longitude_livraison=-17.4467,
            )
        assert "n'est plus disponible" in str(exc.value)

    def test_transitions_etats_et_interdictions(self, donnees_test):
        client = donnees_test["client"]
        gerant = donnees_test["gerant"]
        etablissement = donnees_test["etablissement"]
        plat1 = donnees_test["plat1"]

        LignePanier.objects.create(client=client, plat=plat1, quantite=1)
        commande = creer_commande_depuis_panier(
            client=client,
            etablissement_id=etablissement.id,
            adresse_livraison="Plateau, Dakar",
            telephone_contact="+221770001122",
            latitude_livraison=14.6928,
            longitude_livraison=-17.4467,
        )

        # Simuler paiement validé
        transitionner_statut_commande(
            commande,
            StatutCommande.CREEE_EN_ATTENTE,
            auteur=client,
            commentaire="Paiement Wave confirmé",
        )

        # 1. Transition illégale : tenter de marquer LIVREE directement depuis CREEE_EN_ATTENTE
        with pytest.raises(TransitionInterdite):
            transitionner_statut_commande(
                commande,
                StatutCommande.LIVREE,
                auteur=gerant,
            )

        # 2. Transition légale : Accepter -> EN_PREPARATION
        accepter_commande_par_restaurant(commande, gerant, delai_minutes=30)
        commande.refresh_from_db()
        assert commande.statut == StatutCommande.EN_PREPARATION
        assert commande.delai_preparation_estime_minutes == 30
        assert commande.heure_debut_preparation is not None

        # 3. Transition légale : Préparer -> PRETE_POUR_RETRAIT
        marquer_commande_prete(commande, gerant)
        commande.refresh_from_db()
        assert commande.statut == StatutCommande.PRETE_POUR_RETRAIT
        assert commande.heure_fin_preparation is not None

    # La validation du PIN est testée dans livraisons/tests (seul le livreur assigné peut la faire).

    def test_permission_refus_restaurant_tiers(self, donnees_test):
        client = donnees_test["client"]
        autre_gerant = donnees_test["autre_client"]  # pas le gérant de cet établissement
        etablissement = donnees_test["etablissement"]
        plat1 = donnees_test["plat1"]

        LignePanier.objects.create(client=client, plat=plat1, quantite=1)
        commande = creer_commande_depuis_panier(
            client=client,
            etablissement_id=etablissement.id,
            adresse_livraison="Dakar",
            telephone_contact="+221770001122",
            latitude_livraison=14.6928,
            longitude_livraison=-17.4467,
        )

        with pytest.raises(AccesRefuse):
            accepter_commande_par_restaurant(commande, autre_gerant)

    def test_commande_hors_zone_dakar_rejetee(self, donnees_test):
        client = donnees_test["client"]
        etablissement = donnees_test["etablissement"]
        plat1 = donnees_test["plat1"]

        LignePanier.objects.create(client=client, plat=plat1, quantite=1)

        # Coordonnées hors région de Dakar (ex: Thiès / Saint-Louis)
        with pytest.raises(ErreurMetier) as exc:
            creer_commande_depuis_panier(
                client=client,
                etablissement_id=etablissement.id,
                adresse_livraison="Thiès ville",
                telephone_contact="+221770001122",
                latitude_livraison=14.790000,
                longitude_livraison=-16.920000,
            )
        assert exc.value.code == "zone_non_eligible"
        assert "cette zone n'est pas encore éligible à la livraison AYYOU" in str(exc.value)

    def test_commande_calcul_frais_progressifs_distance(self, donnees_test):
        client = donnees_test["client"]
        etablissement = donnees_test["etablissement"]
        plat1 = donnees_test["plat1"]

        # Établissement situé au Plateau
        etablissement.latitude = 14.670000
        etablissement.longitude = -17.430000
        etablissement.save()

        LignePanier.objects.create(client=client, plat=plat1, quantite=1)

        # Client à Mermoz (environ 6 km)
        commande = creer_commande_depuis_panier(
            client=client,
            etablissement_id=etablissement.id,
            adresse_livraison="Mermoz, Dakar",
            telephone_contact="+221770001122",
            latitude_livraison=14.710000,
            longitude_livraison=-17.470000,
        )

        assert commande.frais_livraison_fcfa >= 1000
        assert commande.frais_livraison_fcfa <= 2000
        assert commande.total_fcfa == commande.sous_total_fcfa + commande.frais_livraison_fcfa
