"""
Traitement des commandes dont un délai est dépassé.

Délais (configurables dans settings / .env) :
- paiement non reçu après DELAI_PAIEMENT_MINUTES                 -> commande annulée ;
- commande payée non acceptée après DELAI_ACCEPTATION_RESTAURANT_MINUTES
                                                                   -> annulée et remboursée ;
- commande prête sans livreur après DELAI_ALERTE_SANS_LIVREUR_MINUTES
                                                                   -> alerte aux administrateurs (une seule fois).

Comment c'est déclenché ? Sans infrastructure supplémentaire :
- le middleware `MiddlewareExpirations` lance `traiter_commandes_expirees()` au plus une fois
  par minute, pendant une requête normale ;
- la commande `python manage.py traiter_expirations` fait la même chose (utilisable avec cron).
Chaque commande est traitée sous verrou : lancer le traitement deux fois en parallèle est sans risque.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from applications.communs.erreurs import ErreurMetier

from .models import Commande, HistoriqueStatutCommande, StatutCommande

logger = logging.getLogger("ayyou.commandes")

CLE_DERNIER_PASSAGE = "ayyou:expirations:dernier_passage"
INTERVALLE_SECONDES = 60
# Nombre maximum de commandes traitées par passage, pour ne jamais ralentir une requête utilisateur.
LOT_MAXIMUM = 20
TITRE_ALERTE_SANS_LIVREUR = "Aucun livreur pour {ref}"


def _limite(minutes: int):
    return timezone.now() - timedelta(minutes=minutes)


def expirer_paiements_non_recus() -> int:
    """Annule les commandes restées sans paiement trop longtemps (après une dernière vérification PayTech)."""
    from applications.paiements.services import verifier_statut_paytech_en_ligne

    nombre = 0
    commandes = Commande.objects.filter(
        statut=StatutCommande.EN_ATTENTE_PAIEMENT, date_creation__lt=_limite(settings.DELAI_PAIEMENT_MINUTES)
    )[:LOT_MAXIMUM]
    for commande in commandes:
        try:
            # La notification PayTech a peut-être simplement du retard : on demande le statut réel.
            if commande.tentatives_paiement.exists():
                verifier_statut_paytech_en_ligne(commande.id)
                commande.refresh_from_db()
            if commande.statut == StatutCommande.EN_ATTENTE_PAIEMENT:
                from .services import transitionner_statut_commande

                transitionner_statut_commande(
                    commande, StatutCommande.REFUSEE_ANNULEE, auteur=None,
                    motif="Paiement non reçu dans les délais.",
                )
                nombre += 1
        except ErreurMetier as erreur:
            logger.warning("Expiration paiement %s ignorée : %s", commande.reference, erreur)
    return nombre


def _date_paiement(commande: Commande):
    """Moment où la commande est devenue payée (passage à CREEE_EN_ATTENTE)."""
    historique = (
        HistoriqueStatutCommande.objects.filter(commande=commande, nouveau_statut=StatutCommande.CREEE_EN_ATTENTE)
        .order_by("-date_transition")
        .first()
    )
    return historique.date_transition if historique else commande.date_creation


def expirer_commandes_non_acceptees() -> int:
    """Annule et rembourse les commandes payées que le restaurant n'a pas acceptées à temps."""
    from .services import annuler_et_rembourser

    nombre = 0
    limite = _limite(settings.DELAI_ACCEPTATION_RESTAURANT_MINUTES)
    for commande in Commande.objects.filter(statut=StatutCommande.CREEE_EN_ATTENTE)[:LOT_MAXIMUM]:
        if _date_paiement(commande) >= limite:
            continue
        try:
            annuler_et_rembourser(
                commande, auteur=None,
                motif="Le restaurant n'a pas accepté la commande à temps.",
            )
            nombre += 1
        except ErreurMetier as erreur:
            logger.warning("Expiration acceptation %s ignorée : %s", commande.reference, erreur)
    return nombre


def alerter_commandes_sans_livreur() -> int:
    """Prévient les administrateurs (une seule fois par commande) quand aucun livreur n'a accepté."""
    from applications.notifications.models import Notification, TypeNotification
    from applications.notifications.services import administrateurs_actifs, creer_notification

    nombre = 0
    commandes = Commande.objects.filter(
        statut=StatutCommande.PRETE_POUR_RETRAIT,
        livraison__isnull=True,
        heure_fin_preparation__lt=_limite(settings.DELAI_ALERTE_SANS_LIVREUR_MINUTES),
    ).select_related("etablissement")[:LOT_MAXIMUM]
    for commande in commandes:
        titre = TITRE_ALERTE_SANS_LIVREUR.format(ref=commande.reference)
        if Notification.objects.filter(reference_commande=commande.reference, titre=titre).exists():
            continue
        for admin in administrateurs_actifs():
            creer_notification(
                destinataire=admin,
                titre=titre,
                message=(
                    f"La commande {commande.reference} ({commande.etablissement.nom}) attend un livreur depuis plus de "
                    f"{settings.DELAI_ALERTE_SANS_LIVREUR_MINUTES} min. Contactez des livreurs de la zone."
                ),
                type_notification=TypeNotification.INFO_SYSTEME,
                reference_commande=commande.reference,
            )
        nombre += 1
    return nombre


def traiter_commandes_expirees() -> dict:
    """Lance les trois traitements et renvoie le nombre de commandes concernées par chacun."""
    return {
        "paiements_expires": expirer_paiements_non_recus(),
        "commandes_non_acceptees": expirer_commandes_non_acceptees(),
        "alertes_sans_livreur": alerter_commandes_sans_livreur(),
    }


def traiter_si_necessaire() -> None:
    """Lance le traitement au plus une fois par minute (le cache garde l'heure du dernier passage)."""
    if not cache.add(CLE_DERNIER_PASSAGE, True, timeout=INTERVALLE_SECONDES):
        return  # déjà fait il y a moins d'une minute
    try:
        resultat = traiter_commandes_expirees()
        if any(resultat.values()):
            logger.info("Expirations traitées : %s", resultat)
    except Exception:
        # Un problème ici ne doit jamais empêcher l'utilisateur d'obtenir sa réponse.
        logger.exception("Erreur pendant le traitement des expirations.")


class MiddlewareExpirations:
    """Middleware Django : déclenche le traitement des expirations pendant les requêtes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        reponse = self.get_response(request)
        traiter_si_necessaire()
        return reponse
