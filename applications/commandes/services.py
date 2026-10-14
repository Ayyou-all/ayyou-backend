"""
Services métier du domaine Commande pour AYYOU.

Responsabilités :
1. Création sécurisée d'une commande à partir du panier avec recalcul des montants.
2. Machine à états formelle et validation stricte des transitions autorisées.
3. Vérification des droits d'action par rôle (Client, Gérant, Livreur, Admin).
4. Journalisation systématique de chaque transition dans l'historique d'audit.
"""

from django.db import transaction
from django.utils import timezone

from applications.communs.erreurs import AccesRefuse, ErreurMetier, TransitionInterdite
from applications.etablissements.models import Etablissement
from applications.panier.models import LignePanier
from applications.panier.services import vider_panier
from applications.utilisateurs.models import Role

from .models import Commande, HistoriqueStatutCommande, LigneCommande, ModePaiement, StatutCommande

# Matrice formelle des transitions autorisées : { EtatInitial: { EtatCible1, EtatCible2, ... } }
TRANSITIONS_COMMANDES_VALIDES: dict[str, set[str]] = {
    StatutCommande.EN_ATTENTE_PAIEMENT: {
        StatutCommande.CREEE_EN_ATTENTE,
        StatutCommande.REFUSEE_ANNULEE,
    },
    StatutCommande.CREEE_EN_ATTENTE: {
        StatutCommande.EN_PREPARATION,
        StatutCommande.REFUSEE_ANNULEE,
    },
    StatutCommande.EN_PREPARATION: {
        StatutCommande.PRETE_POUR_RETRAIT,
        StatutCommande.REFUSEE_ANNULEE,
    },
    StatutCommande.PRETE_POUR_RETRAIT: {
        StatutCommande.COURSE_ASSIGNEE,
        StatutCommande.REFUSEE_ANNULEE,
    },
    StatutCommande.COURSE_ASSIGNEE: {
        StatutCommande.EN_VERIFICATION,
        StatutCommande.REFUSEE_ANNULEE,
        StatutCommande.PRETE_POUR_RETRAIT,  # réassignation si le livreur annule
    },
    StatutCommande.EN_VERIFICATION: {
        StatutCommande.EN_LIVRAISON,
        StatutCommande.REFUSEE_ANNULEE,
    },
    StatutCommande.EN_LIVRAISON: {
        StatutCommande.ARRIVE_CLIENT,
        StatutCommande.ECHEC_LIVRAISON,
    },
    StatutCommande.ARRIVE_CLIENT: {
        StatutCommande.LIVREE,
        StatutCommande.ECHEC_LIVRAISON,
    },
    StatutCommande.LIVREE: set(),
    StatutCommande.REFUSEE_ANNULEE: set(),
    StatutCommande.ECHEC_LIVRAISON: set(),
}


@transaction.atomic
def creer_commande_depuis_panier(
    client,
    etablissement_id: int,
    adresse_livraison: str,
    telephone_contact: str,
    instructions_livraison: str = "",
    mode_paiement: str = ModePaiement.WAVE,
    latitude_livraison=None,
    longitude_livraison=None,
    source_video_id: str = "",
    articles_payload: list = None,
) -> Commande:
    """
    Crée une commande pour un établissement donné à partir des lignes du panier du client (ou des articles transmis).
    Tous les prix et frais sont obligatoirement vérifiés et recalculés depuis la base de données.
    """
    etablissement = Etablissement.objects.filter(pk=etablissement_id).first()
    if etablissement is None:
        raise ErreurMetier("Établissement introuvable.", code="etablissement_introuvable")

    if not etablissement.peut_recevoir_commandes:
        raise ErreurMetier(
            f"L'établissement « {etablissement.nom} » n'est pas ouvert ou n'est pas encore validé.",
            code="etablissement_ferme",
        )

    sous_total_fcfa = 0
    lignes_a_creer = []

    if articles_payload:
        from applications.catalogue.models import Plat
        plat_ids = [a["plat_id"] for a in articles_payload if "plat_id" in a]
        plats_db = {
            p.id: p
            for p in Plat.objects.filter(
                id__in=plat_ids,
                etablissement=etablissement,
            )
        }
        for item in articles_payload:
            pid = item.get("plat_id")
            if pid not in plats_db:
                continue
            plat = plats_db[pid]
            if not plat.est_commandable:
                raise ErreurMetier(
                    f"Le plat « {plat.nom} » n'est plus disponible.",
                    code="plat_indisponible",
                    details={"plat_id": plat.id, "plat_nom": plat.nom},
                )
            quantite = max(1, int(item.get("quantite", 1)))
            prix_unitaire = plat.prix_fcfa
            sous_total_fcfa += prix_unitaire * quantite
            lignes_a_creer.append(
                {
                    "plat": plat,
                    "nom_plat": plat.nom,
                    "prix_unitaire_fcfa": prix_unitaire,
                    "quantite": quantite,
                    "instructions_speciales": item.get("instructions_speciales", ""),
                }
            )

        if not lignes_a_creer:
            raise ErreurMetier(
                "Aucun article valide trouvé pour cet établissement.",
                code="panier_vide",
            )
    else:
        lignes_panier = list(
            LignePanier.objects.select_for_update()
            .filter(client=client, plat__etablissement=etablissement)
            .select_related("plat")
        )

        if not lignes_panier:
            raise ErreurMetier(
                "Votre panier pour cet établissement est vide.",
                code="panier_vide",
            )

        for ligne in lignes_panier:
            plat = ligne.plat
            if not plat.est_commandable:
                raise ErreurMetier(
                    f"Le plat « {plat.nom} » n'est plus disponible.",
                    code="plat_indisponible",
                    details={"plat_id": plat.id, "plat_nom": plat.nom},
                )
            prix_unitaire = plat.prix_fcfa
            sous_total_fcfa += prix_unitaire * ligne.quantite
            lignes_a_creer.append(
                {
                    "plat": plat,
                    "nom_plat": plat.nom,
                    "prix_unitaire_fcfa": prix_unitaire,
                    "quantite": ligne.quantite,
                    "instructions_speciales": ligne.instructions_speciales,
                }
            )

    frais_livraison_fcfa = etablissement.frais_livraison_fcfa
    total_fcfa = sous_total_fcfa + frais_livraison_fcfa

    commande = Commande.objects.create(
        client=client,
        etablissement=etablissement,
        statut=StatutCommande.EN_ATTENTE_PAIEMENT,
        mode_paiement=mode_paiement,
        adresse_livraison=adresse_livraison.strip(),
        telephone_contact=telephone_contact.strip() or client.telephone,
        instructions_livraison=instructions_livraison.strip(),
        latitude_livraison=latitude_livraison,
        longitude_livraison=longitude_livraison,
        sous_total_fcfa=sous_total_fcfa,
        frais_livraison_fcfa=frais_livraison_fcfa,
        total_fcfa=total_fcfa,
        source_video_id=source_video_id.strip(),
    )

    for item in lignes_a_creer:
        LigneCommande.objects.create(
            commande=commande,
            plat=item["plat"],
            nom_plat=item["nom_plat"],
            prix_unitaire_fcfa=item["prix_unitaire_fcfa"],
            quantite=item["quantite"],
            instructions_speciales=item["instructions_speciales"],
        )

    # Vider le sous-panier de cet établissement
    vider_panier(client, etablissement_id=etablissement.id)

    # Trace d'audit initiale
    HistoriqueStatutCommande.objects.create(
        commande=commande,
        ancien_statut="",
        nouveau_statut=StatutCommande.EN_ATTENTE_PAIEMENT,
        auteur=client,
        commentaire="Création de la commande, en attente de paiement mobile.",
    )

    return commande


@transaction.atomic
def transitionner_statut_commande(
    commande: Commande,
    nouveau_statut: str,
    auteur,
    commentaire: str = "",
    motif: str = "",
    delai_minutes: int | None = None,
) -> Commande:
    """
    Applique une transition de statut à la commande après validation de la machine à états.
    """
    ancien_statut = commande.statut

    if ancien_statut == nouveau_statut:
        return commande

    cibles_possibles = TRANSITIONS_COMMANDES_VALIDES.get(ancien_statut, set())
    if nouveau_statut not in cibles_possibles:
        raise TransitionInterdite(
            f"Transition interdite : impossible de passer de « {ancien_statut} » à « {nouveau_statut} ».",
            details={"ancien_statut": ancien_statut, "nouveau_statut": nouveau_statut},
        )

    maintenant = timezone.now()
    champs_maj = ["statut", "date_modification"]

    if nouveau_statut == StatutCommande.EN_PREPARATION:
        commande.heure_debut_preparation = maintenant
        champs_maj.append("heure_debut_preparation")
        if delai_minutes is not None:
            commande.delai_preparation_estime_minutes = delai_minutes
            champs_maj.append("delai_preparation_estime_minutes")

    elif nouveau_statut == StatutCommande.PRETE_POUR_RETRAIT:
        commande.heure_fin_preparation = maintenant
        champs_maj.append("heure_fin_preparation")

    elif nouveau_statut == StatutCommande.EN_LIVRAISON:
        commande.heure_depart_livraison = maintenant
        champs_maj.append("heure_depart_livraison")

    elif nouveau_statut == StatutCommande.LIVREE:
        commande.heure_livraison_effective = maintenant
        champs_maj.append("heure_livraison_effective")

    elif nouveau_statut in {StatutCommande.REFUSEE_ANNULEE, StatutCommande.ECHEC_LIVRAISON}:
        if not motif:
            raise ErreurMetier("Un motif est obligatoire pour refuser, annuler ou déclarer un échec de livraison.")
        commande.motif_refus_ou_annulation = motif
        champs_maj.append("motif_refus_ou_annulation")

    commande.statut = nouveau_statut
    commande.save(update_fields=champs_maj)

    HistoriqueStatutCommande.objects.create(
        commande=commande,
        ancien_statut=ancien_statut,
        nouveau_statut=nouveau_statut,
        auteur=auteur,
        commentaire=commentaire or motif,
    )

    return commande


# --- Actions spécifiques par acteur ---


def accepter_commande_par_restaurant(commande: Commande, gerant, delai_minutes: int = 25) -> Commande:
    """Action Gérant (T02) : Accepter la commande et lancer la préparation."""
    if not (gerant.is_superuser or commande.etablissement.gerant_id == gerant.id):
        raise AccesRefuse("Vous ne pouvez accepter que les commandes de votre propre établissement.")

    return transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.EN_PREPARATION,
        auteur=gerant,
        commentaire=f"Commande acceptée par le restaurant. Délai estimé : {delai_minutes} min.",
        delai_minutes=delai_minutes,
    )


def refuser_commande_par_restaurant(commande: Commande, gerant, motif: str) -> Commande:
    """Action Gérant (T03) : Refuser la commande (rupture ingrédient, surcharge)."""
    if not (gerant.is_superuser or commande.etablissement.gerant_id == gerant.id):
        raise AccesRefuse("Vous ne pouvez refuser que les commandes de votre propre établissement.")

    if not motif.strip():
        raise ErreurMetier("Le motif de refus est obligatoire.", code="motif_obligatoire")

    return transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.REFUSEE_ANNULEE,
        auteur=gerant,
        motif=motif.strip(),
        commentaire=f"Refus restaurant : {motif}",
    )


def marquer_commande_prete(commande: Commande, gerant) -> Commande:
    """Action Gérant (T04) : Préparation terminée et emballée au comptoir."""
    if not (gerant.is_superuser or commande.etablissement.gerant_id == gerant.id):
        raise AccesRefuse("Vous ne pouvez gérer que les commandes de votre propre établissement.")

    return transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.PRETE_POUR_RETRAIT,
        auteur=gerant,
        commentaire="Plats prêts et emballés au comptoir de retrait.",
    )


def valider_reception_client_par_pin(commande: Commande, livreur, code_pin_saisi: str) -> Commande:
    """
    Action Livreur (T09) : Saisie exacte du code PIN de 4 chiffres du client.
    Règle P1 résolue : compare rigoureusement le code saisi avec code_livraison_pin.
    """
    if not (livreur.is_superuser or livreur.role == Role.LIVREUR):
        raise AccesRefuse("Seul un livreur peut valider la remise de commande.")

    code_nettoye = str(code_pin_saisi).strip()
    if code_nettoye != commande.code_livraison_pin:
        raise ErreurMetier(
            "Code PIN de sécurité incorrect. Veuillez demander au client son code à 4 chiffres.",
            code="code_pin_invalide",
        )

    return transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.LIVREE,
        auteur=livreur,
        commentaire="Code PIN client vérifié avec succès. Commande livrée.",
    )
