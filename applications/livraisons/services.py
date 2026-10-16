"""
Services métier pour le domaine Livraison et l'espace Livreur AYYOU.

Règles de sécurité appliquées partout :
1. Un livreur doit être validé (compte actif + profil ACTIF) pour travailler.
2. Seul le livreur assigné à une livraison peut la faire avancer.
3. Les opérations critiques verrouillent la commande en base (select_for_update)
   pour éviter que deux requêtes simultanées ne la modifient en même temps.
"""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from applications.commandes.models import Commande, LigneCommande, StatutCommande
from applications.commandes.services import transitionner_statut_commande
from applications.communs.erreurs import AccesRefuse, ErreurMetier

from .models import DisponibiliteLivreur, EtapeLivraison, Livraison, ProfilLivreur
from .tarification import calculer_gain_livreur

ETAPES_TERMINEES = [EtapeLivraison.LIVREE, EtapeLivraison.ECHOUEE]


def obtenir_profil_livreur(utilisateur) -> ProfilLivreur:
    """Récupère le profil du livreur connecté (créé vide s'il manque, jamais validé d'office)."""
    profil = getattr(utilisateur, "profil_livreur", None)
    if profil is not None:
        return profil
    if getattr(utilisateur, "role", None) == "LIVREUR":
        profil, _ = ProfilLivreur.objects.get_or_create(utilisateur=utilisateur)
        return profil
    raise AccesRefuse("Aucun profil de livreur n'est associé à ce compte.")


def verifier_livreur_valide(profil_livreur: ProfilLivreur) -> None:
    """Bloque toute action d'un livreur non validé, suspendu ou banni."""
    if not profil_livreur.est_valide:
        raise AccesRefuse("Votre profil livreur n'est pas validé par AYYOU. Vous ne pouvez pas effectuer de course.")


def obtenir_livraison_active(profil_livreur: ProfilLivreur) -> Livraison | None:
    """La livraison en cours du livreur (une seule possible à la fois)."""
    return (
        Livraison.objects.filter(livreur=profil_livreur)
        .exclude(etape__in=ETAPES_TERMINEES)
        .select_related("commande", "commande__etablissement", "commande__client")
        .first()
    )


def exiger_livraison_active(profil_livreur: ProfilLivreur) -> Livraison:
    livraison = obtenir_livraison_active(profil_livreur)
    if livraison is None:
        raise ErreurMetier("Aucune livraison active.", code="aucune_livraison")
    return livraison


def lister_courses_disponibles(profil_livreur: ProfilLivreur):
    """
    Commandes prêtes au comptoir et encore sans livreur.
    Un livreur non validé ou hors ligne ne reçoit aucune course.
    """
    if not profil_livreur.peut_recevoir_courses:
        return Commande.objects.none()

    return (
        Commande.objects.filter(statut=StatutCommande.PRETE_POUR_RETRAIT, livraison__isnull=True)
        .select_related("etablissement")
        .prefetch_related("lignes")
        .order_by("heure_fin_preparation", "date_creation")
    )


@transaction.atomic
def accepter_mission_livraison(commande: Commande, profil_livreur: ProfilLivreur) -> Livraison:
    """
    Le livreur accepte une course. Le serveur décide qui gagne :
    la commande et le profil sont verrouillés, le premier livreur valide l'emporte.
    """
    profil = ProfilLivreur.objects.select_for_update().select_related("utilisateur").get(pk=profil_livreur.pk)
    verifier_livreur_valide(profil)
    if profil.disponibilite != DisponibiliteLivreur.EN_LIGNE:
        raise ErreurMetier(
            "Vous devez être « En ligne » et sans course en cours pour accepter une mission.",
            code="livreur_non_disponible",
        )
    if obtenir_livraison_active(profil) is not None:
        raise ErreurMetier("Vous avez déjà une course en cours.", code="livreur_occupe")

    commande_verrouillee = Commande.objects.select_for_update().get(pk=commande.pk)
    if commande_verrouillee.statut != StatutCommande.PRETE_POUR_RETRAIT:
        raise ErreurMetier("Cette course n'est plus disponible.", code="course_indisponible")
    if Livraison.objects.filter(commande=commande_verrouillee).exists():
        raise ErreurMetier("Cette course a déjà été acceptée par un autre livreur.", code="course_deja_assignee")

    livraison = Livraison.objects.create(
        commande=commande_verrouillee,
        livreur=profil,
        etape=EtapeLivraison.VERS_RESTAURANT,
        gain_livreur_fcfa=calculer_gain_livreur(commande_verrouillee.frais_livraison_fcfa),
    )
    transitionner_statut_commande(
        commande=commande_verrouillee,
        nouveau_statut=StatutCommande.COURSE_ASSIGNEE,
        auteur=profil.utilisateur,
        commentaire=f"Course acceptée par le livreur {profil.utilisateur.nom_complet}.",
    )
    profil.disponibilite = DisponibiliteLivreur.OCCUPE
    profil.save(update_fields=["disponibilite"])
    return livraison


@transaction.atomic
def pointer_article_au_guichet(livraison: Livraison, ligne_id: int, est_verifie: bool) -> LigneCommande:
    """Le livreur coche un article au comptoir du restaurant."""
    verifier_livreur_valide(livraison.livreur)
    commande = Commande.objects.select_for_update().get(pk=livraison.commande_id)
    if commande.statut not in (StatutCommande.COURSE_ASSIGNEE, StatutCommande.EN_VERIFICATION):
        raise ErreurMetier("La vérification des articles n'est plus possible à cette étape.", code="etape_invalide")

    ligne = LigneCommande.objects.filter(pk=ligne_id, commande=commande).first()
    if ligne is None:
        raise ErreurMetier("Article introuvable pour cette commande.", code="article_introuvable")
    ligne.est_verifie_par_livreur = est_verifie
    ligne.save(update_fields=["est_verifie_par_livreur"])

    if commande.statut == StatutCommande.COURSE_ASSIGNEE:
        transitionner_statut_commande(
            commande=commande,
            nouveau_statut=StatutCommande.EN_VERIFICATION,
            auteur=livraison.livreur.utilisateur,
            commentaire="Livreur présent au restaurant. Vérification des articles en cours.",
        )
        livraison.etape = EtapeLivraison.VERIFICATION_ARTICLES
        livraison.save(update_fields=["etape"])
    return ligne


@transaction.atomic
def demarrer_trajet_vers_client(livraison: Livraison) -> Livraison:
    """Tous les articles sont vérifiés : le livreur part chez le client."""
    verifier_livreur_valide(livraison.livreur)
    commande = Commande.objects.select_for_update().get(pk=livraison.commande_id)
    livraison.refresh_from_db()
    if livraison.date_remise_restaurant is None:
        raise ErreurMetier(
            "Le restaurant doit d'abord confirmer qu'il vous a remis la commande.",
            code="remise_non_confirmee",
        )
    if commande.lignes.filter(est_verifie_par_livreur=False).exists():
        raise ErreurMetier(
            "Veuillez vérifier l'ensemble des articles au comptoir avant le départ.",
            code="articles_non_verifies",
        )

    transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.EN_LIVRAISON,
        auteur=livraison.livreur.utilisateur,
        commentaire="Colis remis au livreur. Départ vers le client.",
    )
    livraison.etape = EtapeLivraison.VERS_CLIENT
    livraison.date_recuperation = timezone.now()
    livraison.save(update_fields=["etape", "date_recuperation"])
    return livraison


@transaction.atomic
def signaler_arrivee_domicile_client(livraison: Livraison) -> Livraison:
    """Le livreur est arrivé à l'adresse du client."""
    verifier_livreur_valide(livraison.livreur)
    commande = Commande.objects.select_for_update().get(pk=livraison.commande_id)
    transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.ARRIVE_CLIENT,
        auteur=livraison.livreur.utilisateur,
        commentaire="Le livreur est arrivé à l'adresse de livraison.",
    )
    livraison.etape = EtapeLivraison.ARRIVE_CLIENT
    livraison.save(update_fields=["etape"])
    return livraison


def livraison_est_bloquee(livraison: Livraison) -> bool:
    """Après trop de PIN erronés, seule l'administration peut débloquer la livraison."""
    return livraison.essais_code_echoues >= settings.NOMBRE_MAX_ESSAIS_CODE_LIVRAISON


def valider_livraison_avec_pin(profil_livreur: ProfilLivreur, code_pin: str) -> Livraison:
    """
    Clôture la livraison du livreur connecté avec le PIN donné par le client.

    Contrôles côté serveur :
    - livreur validé et assigné à cette livraison (on ne cherche que SA livraison) ;
    - commande en cours de livraison ou livreur arrivé chez le client ;
    - au maximum N essais (compteur en base), puis blocage jusqu'à intervention du support.

    Le compteur d'échecs est enregistré AVANT de lever l'erreur, hors du bloc atomique,
    sinon l'annulation de la transaction effacerait l'essai raté.
    """
    maximum = settings.NOMBRE_MAX_ESSAIS_CODE_LIVRAISON
    with transaction.atomic():
        verifier_livreur_valide(profil_livreur)
        livraison = (
            Livraison.objects.select_for_update()
            .filter(livreur=profil_livreur)
            .exclude(etape__in=ETAPES_TERMINEES)
            .first()
        )
        if livraison is None:
            raise ErreurMetier("Aucune livraison active.", code="aucune_livraison")

        commande = Commande.objects.select_for_update().get(pk=livraison.commande_id)
        if commande.statut not in (StatutCommande.EN_LIVRAISON, StatutCommande.ARRIVE_CLIENT):
            raise ErreurMetier("Le PIN ne peut être saisi qu'une fois en route vers le client.", code="etape_invalide")
        if livraison_est_bloquee(livraison):
            raise ErreurMetier(
                "Livraison bloquée après trop de codes erronés. Contactez le support AYYOU.",
                code="livraison_bloquee",
            )

        if str(code_pin).strip() == commande.code_livraison_pin:
            transitionner_statut_commande(
                commande=commande,
                nouveau_statut=StatutCommande.LIVREE,
                auteur=profil_livreur.utilisateur,
                commentaire="Code PIN du client vérifié. Commande livrée.",
            )
            livraison.etape = EtapeLivraison.LIVREE
            livraison.date_livraison = timezone.now()
            livraison.save(update_fields=["etape", "date_livraison"])
            profil_livreur.disponibilite = DisponibiliteLivreur.EN_LIGNE
            profil_livreur.save(update_fields=["disponibilite"])
            return livraison

        livraison.essais_code_echoues += 1
        livraison.save(update_fields=["essais_code_echoues"])
        essais_restants = max(0, maximum - livraison.essais_code_echoues)

    if essais_restants == 0:
        raise ErreurMetier(
            "Code PIN incorrect. Nombre maximal d'essais atteint : la livraison est bloquée, contactez le support AYYOU.",
            code="livraison_bloquee",
        )
    raise ErreurMetier(f"Code PIN incorrect. Il vous reste {essais_restants} essai(s).", code="code_pin_invalide")


def changer_disponibilite(profil_livreur: ProfilLivreur, disponibilite: str) -> ProfilLivreur:
    """Interrupteur En ligne / Hors ligne. Un livreur non validé ne peut pas passer en ligne."""
    if disponibilite not in (DisponibiliteLivreur.EN_LIGNE, DisponibiliteLivreur.HORS_LIGNE):
        raise ErreurMetier("Disponibilité invalide.", code="disponibilite_invalide")
    if obtenir_livraison_active(profil_livreur) is not None:
        raise ErreurMetier("Terminez votre course en cours avant de changer de disponibilité.", code="livreur_occupe")
    if disponibilite == DisponibiliteLivreur.EN_LIGNE:
        verifier_livreur_valide(profil_livreur)

    profil_livreur.disponibilite = disponibilite
    profil_livreur.save(update_fields=["disponibilite"])
    return profil_livreur


def mettre_a_jour_position_gps(profil_livreur: ProfilLivreur, latitude: float, longitude: float):
    """Enregistre la position GPS réelle envoyée par le téléphone du livreur."""
    profil_livreur.latitude = latitude
    profil_livreur.longitude = longitude
    profil_livreur.date_derniere_position = timezone.now()
    profil_livreur.save(update_fields=["latitude", "longitude", "date_derniere_position"])
