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
        StatutCommande.LIVREE,
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


def obtenir_etablissement_recevable(etablissement_id: int) -> Etablissement:
    """L'établissement doit exister, être validé, ouvert et dans ses horaires."""
    etablissement = Etablissement.objects.filter(pk=etablissement_id).first()
    if etablissement is None:
        raise ErreurMetier("Établissement introuvable.", code="etablissement_introuvable")
    if not etablissement.peut_recevoir_commandes:
        raise ErreurMetier(
            f"« {etablissement.nom} » ne prend pas de commande pour le moment (fermé ou non validé).",
            code="etablissement_ferme",
        )
    return etablissement


def preparer_lignes_commande(etablissement: Etablissement, articles: list) -> tuple[list, int]:
    """
    Vérifie chaque article demandé et calcule le sous-total avec les prix ACTUELS en base.
    `articles` : [{"plat_id": 12, "quantite": 2, "instructions_speciales": ""}, ...]
    Renvoie (lignes à créer, sous-total en FCFA).
    """
    from applications.catalogue.models import Plat

    identifiants = [article["plat_id"] for article in articles]
    plats = {plat.id: plat for plat in Plat.objects.filter(id__in=identifiants, etablissement=etablissement)}

    lignes = []
    sous_total_fcfa = 0
    for article in articles:
        plat = plats.get(article["plat_id"])
        if plat is None:
            raise ErreurMetier(
                f"Le plat n°{article['plat_id']} n'appartient pas à cet établissement.",
                code="plat_invalide",
                details={"plat_id": article["plat_id"]},
            )
        if not plat.est_commandable:
            raise ErreurMetier(
                f"Le plat « {plat.nom} » n'est plus disponible.",
                code="plat_indisponible",
                details={"plat_id": plat.id, "plat_nom": plat.nom},
            )
        quantite = article["quantite"]
        sous_total_fcfa += plat.prix_fcfa * quantite
        lignes.append({
            "plat": plat,
            "nom_plat": plat.nom,
            "prix_unitaire_fcfa": plat.prix_fcfa,
            "quantite": quantite,
            "instructions_speciales": article.get("instructions_speciales", ""),
        })

    if not lignes:
        raise ErreurMetier("Le panier ne contient aucun article pour cet établissement.", code="panier_vide")
    return lignes, sous_total_fcfa


def articles_depuis_panier(client, etablissement: Etablissement) -> list:
    """Transforme les lignes du panier serveur d'un restaurant en liste d'articles."""
    return [
        {"plat_id": ligne.plat_id, "quantite": ligne.quantite, "instructions_speciales": ligne.instructions_speciales}
        for ligne in LignePanier.objects.filter(client=client, plat__etablissement=etablissement)
    ]


def estimer_montants_commande(etablissement_id: int, articles: list, latitude, longitude) -> dict:
    """
    Montants exacts AVANT paiement. La création de commande utilise les mêmes fonctions :
    le total affiché au client est donc exactement celui envoyé à PayTech.
    """
    from applications.livraisons.tarification import calculer_frais_livraison_commande

    etablissement = obtenir_etablissement_recevable(etablissement_id)
    _, sous_total_fcfa = preparer_lignes_commande(etablissement, articles)
    frais_livraison_fcfa = calculer_frais_livraison_commande(etablissement, latitude, longitude)
    return {
        "sous_total_fcfa": sous_total_fcfa,
        "frais_livraison_fcfa": frais_livraison_fcfa,
        "total_fcfa": sous_total_fcfa + frais_livraison_fcfa,
    }


@transaction.atomic
def creer_commande_depuis_panier(
    client,
    etablissement_id: int,
    adresse_livraison: str,
    latitude_livraison,
    longitude_livraison,
    telephone_contact: str = "",
    repere_livraison: str = "",
    instructions_livraison: str = "",
    mode_paiement: str = ModePaiement.WAVE,
    source_video_id: str = "",
    articles_payload: list | None = None,
) -> Commande:
    """
    Crée une commande pour un établissement à partir des articles transmis
    (ou, à défaut, du panier serveur du client pour cet établissement).
    Prix, frais et total sont TOUJOURS recalculés côté serveur.
    """
    from applications.livraisons.tarification import calculer_frais_livraison_commande

    etablissement = obtenir_etablissement_recevable(etablissement_id)
    articles = articles_payload or articles_depuis_panier(client, etablissement)
    lignes_a_creer, sous_total_fcfa = preparer_lignes_commande(etablissement, articles)
    frais_livraison_fcfa = calculer_frais_livraison_commande(etablissement, latitude_livraison, longitude_livraison)

    telephone = (telephone_contact or client.telephone or "").strip()
    if not telephone:
        raise ErreurMetier("Un numéro de téléphone est nécessaire pour la livraison.", code="telephone_obligatoire")

    commande = Commande.objects.create(
        client=client,
        etablissement=etablissement,
        statut=StatutCommande.EN_ATTENTE_PAIEMENT,
        mode_paiement=mode_paiement,
        adresse_livraison=adresse_livraison.strip(),
        repere_livraison=repere_livraison.strip(),
        telephone_contact=telephone,
        instructions_livraison=instructions_livraison.strip(),
        latitude_livraison=latitude_livraison,
        longitude_livraison=longitude_livraison,
        sous_total_fcfa=sous_total_fcfa,
        frais_livraison_fcfa=frais_livraison_fcfa,
        total_fcfa=sous_total_fcfa + frais_livraison_fcfa,
        source_video_id=source_video_id.strip(),
    )
    for ligne in lignes_a_creer:
        LigneCommande.objects.create(commande=commande, **ligne)

    # Le panier de ce restaurant est vidé : la commande en attente de paiement le remplace.
    vider_panier(client, etablissement_id=etablissement.id)

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

    if nouveau_statut == StatutCommande.CREEE_EN_ATTENTE:
        try:
            from applications.notifications.services import creer_notification
            from applications.notifications.models import TypeNotification
            if commande.etablissement and commande.etablissement.gerant:
                creer_notification(
                    destinataire=commande.etablissement.gerant,
                    titre=f"Nouvelle commande payée {commande.reference} !",
                    message=f"Commande de {commande.total_fcfa} FCFA par {commande.client.nom_complet if commande.client else 'Client'}.",
                    type_notification=TypeNotification.COMMANDE_NOUVELLE,
                    texte_vocal=f"Nouvelle commande payée {commande.reference}",
                    reference_commande=commande.reference,
                )
            if commande.client:
                creer_notification(
                    destinataire=commande.client,
                    titre=f"Paiement validé pour {commande.reference}",
                    message=f"Votre commande auprès de {commande.etablissement.nom} a été confirmée et transmise en cuisine.",
                    type_notification=TypeNotification.COMMANDE_EN_PREPARATION,
                    texte_vocal="Paiement validé avec succès",
                    reference_commande=commande.reference,
                )
        except Exception as e:
            import logging
            logging.getLogger("ayyou.commandes").warning(f"Erreur notification post-paiement: {e}")

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


# La clôture par code PIN est gérée par applications/livraisons/services.py
# (valider_livraison_avec_pin) : seul le livreur assigné peut la faire.
