"""
Services métier du domaine Commande pour AYYOU.

Responsabilités :
1. Création sécurisée d'une commande à partir du panier avec recalcul des montants.
2. Machine à états formelle et validation stricte des transitions autorisées.
3. Vérification des droits d'action par rôle (Client, Gérant, Livreur, Admin).
4. Journalisation systématique de chaque transition dans l'historique d'audit.
"""

from django.conf import settings
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
        commission_plateforme_fcfa=int(sous_total_fcfa * settings.COMMISSION_RESTAURANT_POURCENT / 100),
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
    Applique une transition de statut après vérification de la machine à états.

    La commande est relue et VERROUILLÉE en base (select_for_update) : si deux requêtes
    arrivent en même temps, la seconde attend la première puis voit le statut à jour.
    L'objet `commande` passé en paramètre est ensuite rafraîchi pour l'appelant.
    """
    verrouillee = Commande.objects.select_for_update().get(pk=commande.pk)
    ancien_statut = verrouillee.statut
    if ancien_statut == nouveau_statut:
        commande.refresh_from_db()
        return commande

    if nouveau_statut not in TRANSITIONS_COMMANDES_VALIDES.get(ancien_statut, set()):
        raise TransitionInterdite(
            f"Transition interdite : impossible de passer de « {ancien_statut} » à « {nouveau_statut} ».",
            details={"ancien_statut": ancien_statut, "nouveau_statut": nouveau_statut},
        )

    maintenant = timezone.now()
    champs_maj = ["statut", "date_modification"]
    if nouveau_statut == StatutCommande.EN_PREPARATION:
        verrouillee.heure_debut_preparation = maintenant
        champs_maj.append("heure_debut_preparation")
        if delai_minutes is not None:
            verrouillee.delai_preparation_estime_minutes = delai_minutes
            champs_maj.append("delai_preparation_estime_minutes")
    elif nouveau_statut == StatutCommande.PRETE_POUR_RETRAIT:
        verrouillee.heure_fin_preparation = maintenant
        champs_maj.append("heure_fin_preparation")
    elif nouveau_statut == StatutCommande.EN_LIVRAISON:
        verrouillee.heure_depart_livraison = maintenant
        champs_maj.append("heure_depart_livraison")
    elif nouveau_statut == StatutCommande.LIVREE:
        verrouillee.heure_livraison_effective = maintenant
        champs_maj.append("heure_livraison_effective")
    elif nouveau_statut in (StatutCommande.REFUSEE_ANNULEE, StatutCommande.ECHEC_LIVRAISON):
        if not motif:
            raise ErreurMetier("Un motif est obligatoire pour refuser, annuler ou déclarer un échec de livraison.")
        verrouillee.motif_refus_ou_annulation = motif
        champs_maj.append("motif_refus_ou_annulation")

    verrouillee.statut = nouveau_statut
    verrouillee.save(update_fields=champs_maj)
    HistoriqueStatutCommande.objects.create(
        commande=verrouillee,
        ancien_statut=ancien_statut,
        nouveau_statut=nouveau_statut,
        auteur=auteur,
        commentaire=commentaire or motif,
    )

    from applications.notifications.services import notifier_changement_statut

    notifier_changement_statut(verrouillee, nouveau_statut, auteur=auteur)
    commande.refresh_from_db()
    return commande


# --- Actions par acteur ---------------------------------------------------------
# Chaque fonction vérifie QUI agit et À QUEL MOMENT, puis délègue la transition.


def _verifier_gerant(commande: Commande, gerant) -> None:
    if commande.etablissement.gerant_id != gerant.id:
        raise AccesRefuse("Vous ne pouvez gérer que les commandes de votre propre établissement.")


def annuler_et_rembourser(commande: Commande, auteur, motif: str, commentaire: str = "") -> Commande:
    """
    Annule la commande puis rembourse ce qui a été payé.
    Si PayTech refuse ou ne répond pas, le paiement reste « confirmé » :
    l'administration le voit dans la liste des paiements à rembourser.
    """
    from applications.notifications.services import creer_notification
    from applications.paiements.services import rembourser_paiements_commande

    commande = transitionner_statut_commande(
        commande, StatutCommande.REFUSEE_ANNULEE, auteur=auteur, motif=motif, commentaire=commentaire
    )
    if commande.tentatives_paiement.filter(statut="CONFIRME").exists():
        rembourse = rembourser_paiements_commande(commande)
        creer_notification(
            destinataire=commande.client,
            titre="Remboursement effectué" if rembourse else "Remboursement en cours",
            message=(
                f"Les {commande.total_fcfa} FCFA de la commande {commande.reference} vous ont été remboursés."
                if rembourse
                else f"Le remboursement de la commande {commande.reference} est en cours de traitement par le support AYYOU."
            ),
            reference_commande=commande.reference,
        )
    return commande


def accepter_commande_par_restaurant(commande: Commande, gerant, delai_minutes: int = 25) -> Commande:
    """Le restaurant accepte une commande payée et annonce son temps de préparation."""
    _verifier_gerant(commande, gerant)
    return transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.EN_PREPARATION,
        auteur=gerant,
        commentaire=f"Commande acceptée par le restaurant. Délai estimé : {delai_minutes} min.",
        delai_minutes=delai_minutes,
    )


def refuser_commande_par_restaurant(commande: Commande, gerant, motif: str) -> Commande:
    """
    Le restaurant refuse une commande payée qu'il n'a pas encore acceptée.
    Après acceptation, seul le support peut annuler (un livreur peut déjà être en route).
    """
    _verifier_gerant(commande, gerant)
    if not motif.strip():
        raise ErreurMetier("Le motif de refus est obligatoire.", code="motif_obligatoire")
    if commande.statut != StatutCommande.CREEE_EN_ATTENTE:
        raise TransitionInterdite("Une commande déjà acceptée ne peut plus être refusée. Contactez le support AYYOU.")
    return annuler_et_rembourser(commande, gerant, motif=motif.strip(), commentaire=f"Refus restaurant : {motif.strip()}")


def marquer_commande_prete(commande: Commande, gerant) -> Commande:
    """Le restaurant a terminé la préparation : la commande est prête au comptoir."""
    _verifier_gerant(commande, gerant)
    return transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.PRETE_POUR_RETRAIT,
        auteur=gerant,
        commentaire="Plats prêts et emballés au comptoir de retrait.",
    )


@transaction.atomic
def confirmer_remise_au_livreur(commande: Commande, gerant) -> Commande:
    """
    Le restaurant confirme avoir remis le sac au livreur assigné.
    Sans cette confirmation, le livreur ne peut pas démarrer le trajet vers le client.
    """
    from applications.livraisons.models import Livraison
    from applications.notifications.services import creer_notification

    _verifier_gerant(commande, gerant)
    commande = Commande.objects.select_for_update().get(pk=commande.pk)
    livraison = Livraison.objects.select_for_update().filter(commande=commande).first()
    if livraison is None:
        raise ErreurMetier("Aucun livreur n'est encore assigné à cette commande.", code="aucun_livreur")
    if commande.statut not in (StatutCommande.COURSE_ASSIGNEE, StatutCommande.EN_VERIFICATION):
        raise TransitionInterdite("La remise n'est possible que lorsque le livreur est au restaurant.")
    if livraison.date_remise_restaurant is None:
        livraison.date_remise_restaurant = timezone.now()
        livraison.save(update_fields=["date_remise_restaurant"])
        HistoriqueStatutCommande.objects.create(
            commande=commande, ancien_statut=commande.statut, nouveau_statut=commande.statut,
            auteur=gerant, commentaire="Le restaurant a remis la commande au livreur.",
        )
        creer_notification(
            destinataire=livraison.livreur.utilisateur,
            titre=f"Commande {commande.reference} remise",
            message="Le restaurant confirme vous avoir remis la commande. Vérifiez les articles puis partez chez le client.",
            reference_commande=commande.reference,
        )
    return commande


STATUTS_ANNULABLES_PAR_CLIENT = (StatutCommande.EN_ATTENTE_PAIEMENT, StatutCommande.CREEE_EN_ATTENTE)


def annuler_commande_par_client(commande: Commande, client, motif: str = "") -> Commande:
    """
    Le client peut annuler tant que le restaurant n'a pas commencé à cuisiner :
    - en attente de paiement : simple annulation ;
    - payée mais pas encore acceptée : annulation + remboursement.
    Ensuite, la nourriture est en préparation : l'annulation passe par le support.
    """
    if commande.client_id != client.id:
        raise AccesRefuse("Vous ne pouvez annuler que vos propres commandes.")
    if commande.statut not in STATUTS_ANNULABLES_PAR_CLIENT:
        raise TransitionInterdite(
            "Le restaurant prépare déjà votre commande : elle ne peut plus être annulée depuis l'application. "
            "Contactez le support AYYOU."
        )
    motif_final = motif.strip() or "Annulée par le client"
    return annuler_et_rembourser(commande, client, motif=motif_final, commentaire=f"Annulation client : {motif_final}")


# La clôture par code PIN est gérée par applications/livraisons/services.py
# (valider_livraison_avec_pin) : seul le livreur assigné peut la faire.
