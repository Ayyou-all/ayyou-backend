"""
Services métier pour le domaine Livraison et espace Coursier AYYOU.

Prend en charge :
- Proposition et acceptation des courses disponibles
- Pointage des articles au comptoir
- Navigation GPS et transitions (vers restaurant, en vérification, en livraison, arrivé client)
- Validation du code PIN de sécurité et remise du colis
"""

from django.db import transaction
from django.utils import timezone

from applications.commandes.models import Commande, LigneCommande, StatutCommande
from applications.commandes.services import (
    transitionner_statut_commande,
    valider_reception_client_par_pin,
)
from applications.communs.erreurs import AccesRefuse, ErreurMetier

from .models import DisponibiliteLivreur, EtapeLivraison, Livraison, ProfilLivreur


def obtenir_profil_livreur(utilisateur) -> ProfilLivreur:
    """Récupère le profil du livreur connecté."""
    profil = getattr(utilisateur, "profil_livreur", None)
    if profil is None:
        if getattr(utilisateur, "role", None) == "LIVREUR" or getattr(utilisateur, "is_superuser", False):
            profil, _ = ProfilLivreur.objects.get_or_create(
                utilisateur=utilisateur,
                defaults={"type_vehicule": "MOTO"}
            )
            return profil
        raise AccesRefuse("Aucun profil de livreur n'est associé à ce compte.")
    return profil


def lister_courses_disponibles(profil_livreur: ProfilLivreur):
    """
    Renvoie les commandes prêtes ou créées par un client qui n'ont pas encore de livreur assigné.
    Le livreur doit être disponible (EN_LIGNE) pour recevoir les courses en temps réel.
    """
    if profil_livreur.disponibilite != DisponibiliteLivreur.EN_LIGNE:
        return Commande.objects.none()

    statuts_eligibles = [
        StatutCommande.PRETE_POUR_RETRAIT,
        StatutCommande.EN_PREPARATION,
    ]
    return (
        Commande.objects.filter(
            statut__in=statuts_eligibles,
            livraison__isnull=True,
        )
        .select_related("etablissement", "client")
        .prefetch_related("lignes")
        .order_by("-date_creation")
    )


@transaction.atomic
def accepter_mission_livraison(commande: Commande, profil_livreur: ProfilLivreur) -> Livraison:
    """
    Action Livreur (T05) : Accepter la mission de livraison proposée.
    Passe la commande à COURSE_ASSIGNEE et le livreur à OCCUPE.
    Verrouille la commande avec select_for_update pour éliminer tout risque de double assignation concurrente.
    """
    if profil_livreur.disponibilite != DisponibiliteLivreur.EN_LIGNE and profil_livreur.disponibilite != DisponibiliteLivreur.OCCUPE:
        raise ErreurMetier(
            "Vous n'êtes pas marqué comme disponible (En ligne).",
            code="livreur_non_disponible",
        )

    # Verrouillage pessimiste de la ligne en base de données
    commande_verrouillee = (
        Commande.objects.select_for_update()
        .filter(pk=commande.pk)
        .first()
    )
    if commande_verrouillee is None:
        raise ErreurMetier("Commande introuvable.", code="commande_introuvable")

    statuts_acceptables = [
        StatutCommande.PRETE_POUR_RETRAIT,
        StatutCommande.EN_PREPARATION,
    ]
    if commande_verrouillee.statut not in statuts_acceptables:
        raise ErreurMetier(
            f"Cette course n'est plus disponible (statut : {commande_verrouillee.statut}).",
            code="course_indisponible",
        )

    livraison_existante = Livraison.objects.filter(commande=commande_verrouillee).first()
    if livraison_existante is not None:
        if livraison_existante.livreur == profil_livreur:
            return livraison_existante
        raise ErreurMetier("Cette commande a déjà été assignée à un autre coursier.", code="course_deja_assignee")

    # Si la commande est encore en préparation, finaliser la transition vers PRETE_POUR_RETRAIT
    if commande_verrouillee.statut == StatutCommande.EN_PREPARATION:
        transitionner_statut_commande(
            commande=commande_verrouillee,
            nouveau_statut=StatutCommande.PRETE_POUR_RETRAIT,
            auteur=profil_livreur.utilisateur,
            commentaire="Commande prête pour retrait par le livreur.",
        )

    # Gain livreur : part des frais de livraison (ex: 80% des frais de livraison, minimum 1000 FCFA)
    gain_fcfa = max(int(commande_verrouillee.frais_livraison_fcfa * 0.8), 1000)

    livraison = Livraison.objects.create(
        commande=commande_verrouillee,
        livreur=profil_livreur,
        etape=EtapeLivraison.VERS_RESTAURANT,
        gain_livreur_fcfa=gain_fcfa,
    )

    # Transition de la commande vers COURSE_ASSIGNEE
    transitionner_statut_commande(
        commande=commande_verrouillee,
        nouveau_statut=StatutCommande.COURSE_ASSIGNEE,
        auteur=profil_livreur.utilisateur,
        commentaire=f"Course acceptée par le livreur {profil_livreur.utilisateur.nom_complet}.",
    )

    # Mettre le livreur en statut OCCUPE
    profil_livreur.disponibilite = DisponibiliteLivreur.OCCUPE
    profil_livreur.save(update_fields=["disponibilite"])

    return livraison


def pointer_article_au_guichet(livraison: Livraison, ligne_id: int, est_verifie: bool) -> LigneCommande:
    """
    Pointage d'un article par le livreur au comptoir du restaurant (T06).
    """
    ligne = LigneCommande.objects.filter(pk=ligne_id, commande=livraison.commande).first()
    if ligne is None:
        raise ErreurMetier("Article introuvable pour cette commande.", code="article_introuvable")

    ligne.est_verifie_par_livreur = est_verifie
    ligne.save(update_fields=["est_verifie_par_livreur"])

    # Passer en statut EN_VERIFICATION si ce n'est pas déjà fait
    if livraison.commande.statut == StatutCommande.COURSE_ASSIGNEE:
        transitionner_statut_commande(
            commande=livraison.commande,
            nouveau_statut=StatutCommande.EN_VERIFICATION,
            auteur=livraison.livreur.utilisateur,
            commentaire="Livreur présent au restaurant. Vérification des articles en cours.",
        )
        livraison.etape = EtapeLivraison.VERIFICATION_ARTICLES
        livraison.save(update_fields=["etape"])

    return ligne


@transaction.atomic
def demarrer_trajet_vers_client(livraison: Livraison) -> Livraison:
    """
    Action Livreur (T07) : Tous les articles sont vérifiés, remise du colis effectuée.
    Le livreur prend la route vers le client.
    """
    commande = livraison.commande

    # Vérification que tous les articles sont cochés
    articles_non_verifies = commande.lignes.filter(est_verifie_par_livreur=False)
    if articles_non_verifies.exists():
        raise ErreurMetier(
            "Veuillez vérifier l'ensemble des articles au comptoir avant le départ.",
            code="articles_non_verifies",
        )

    transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.EN_LIVRAISON,
        auteur=livraison.livreur.utilisateur,
        commentaire="Colis remis au coursier. Départ en livraison vers le domicile client.",
    )

    livraison.etape = EtapeLivraison.VERS_CLIENT
    livraison.date_recuperation = timezone.now()
    livraison.save(update_fields=["etape", "date_recuperation"])

    return livraison


def signaler_arrivee_domicile_client(livraison: Livraison) -> Livraison:
    """Action Livreur (T08) : Arrivé devant l'adresse du client."""
    commande = livraison.commande

    transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.ARRIVE_CLIENT,
        auteur=livraison.livreur.utilisateur,
        commentaire="Le coursier est arrivé au pied de l'adresse de livraison.",
    )

    livraison.etape = EtapeLivraison.ARRIVE_CLIENT
    livraison.save(update_fields=["etape"])
    return livraison


@transaction.atomic
def valider_livraison_avec_pin(livraison: Livraison, code_pin: str) -> Livraison:
    """
    Action Livreur (T09) : Saisie du code PIN client et clôture finale de la livraison.
    Libère le coursier (redevient EN_LIGNE).
    """
    commande = Commande.objects.get(pk=livraison.commande_id)
    livraison.commande = commande
    livreur = livraison.livreur

    try:
        valider_reception_client_par_pin(commande, livreur.utilisateur, code_pin)
    except ErreurMetier as e:
        livraison.essais_code_echoues += 1
        livraison.save(update_fields=["essais_code_echoues"])
        raise e

    livraison.etape = EtapeLivraison.LIVREE
    livraison.date_livraison = timezone.now()
    livraison.save(update_fields=["etape", "date_livraison"])

    # Le coursier redevient disponible pour de nouvelles courses
    livreur.disponibilite = DisponibiliteLivreur.EN_LIGNE
    livreur.save(update_fields=["disponibilite"])

    return livraison


def mettre_a_jour_position_gps(profil_livreur: ProfilLivreur, latitude: float, longitude: float):
    """Met à jour les coordonnées temps réel pour le suivi GPS Leaflet sur Dakar."""
    profil_livreur.latitude = latitude
    profil_livreur.longitude = longitude
    profil_livreur.date_derniere_position = timezone.now()
    profil_livreur.save(update_fields=["latitude", "longitude", "date_derniere_position"])
