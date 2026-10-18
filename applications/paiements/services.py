"""
Services du domaine Paiement pour AYYOU (intégration PayTech Sénégal : Wave, Orange Money).

API PayTech utilisées :
- Demande de paiement : POST {PAYTECH_URL_BASE}/payment/request-payment
- Statut               : GET  {PAYTECH_URL_BASE}/payment/get-status?token_payment=...
- Remboursement        : POST {PAYTECH_URL_BASE}/payment/refund-payment
- Notification (IPN)   : PayTech appelle /api/paiements/webhook-ipn/
    - succès : type_event == "sale_complete"
    - signature HMAC : HMAC-SHA256(item_price|ref_command|API_KEY, clé = API_SECRET) == hmac_compute
    - ou hash des clés : SHA256(API_KEY) == api_key_sha256 et SHA256(API_SECRET) == api_secret_sha256

Règles de sécurité :
1. Sans clés PayTech configurées, AUCUNE notification n'est acceptée.
2. Le montant notifié doit être égal au montant attendu de la tentative.
3. Une commande n'a qu'une seule tentative de paiement active.
4. Un paiement reçu alors que la commande est déjà payée ou annulée est remboursé.
"""

import hashlib
import hmac
import json
import logging
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from applications.commandes.models import Commande, StatutCommande
from applications.commandes.services import transitionner_statut_commande
from applications.communs.erreurs import ErreurMetier, ServiceExterneIndisponible

from .models import StatutPaiement, TentativePaiement

logger = logging.getLogger("ayyou.paiements")


def paytech_est_configure() -> bool:
    return bool(settings.PAYTECH_CLE_API and settings.PAYTECH_CLE_SECRETE)


def _en_tetes_paytech() -> dict:
    return {
        "API_KEY": settings.PAYTECH_CLE_API,
        "API_SECRET": settings.PAYTECH_CLE_SECRETE,
        "Accept": "application/json",
    }


def _url_retour_https(url_cible: str) -> str:
    """
    PayTech exige des URLs de retour en HTTPS.
    En local (http://localhost), on passe par un pont de redirection HTTPS public.
    """
    if url_cible.startswith("https://") and "localhost" not in url_cible and "127.0.0.1" not in url_cible:
        return url_cible
    return f"https://httpbin.org/redirect-to?url={quote(url_cible, safe='')}"


def _construire_url_retour(url_client: str, commande: Commande, parametre: str) -> str:
    """URL vers l'écran de suivi de la commande, avec ?paiement=succes ou ?paiement=en_attente."""
    if not url_client.startswith(("http://", "https://")):
        url_client = f"{settings.URL_FRONTEND.rstrip('/')}/commandes/suivi/{commande.id}"
    if "paiement=" not in url_client:
        separateur = "&" if "?" in url_client else "?"
        url_client = f"{url_client}{separateur}paiement={parametre}"
    return _url_retour_https(url_client)


def initier_demande_paiement_paytech(
    commande: Commande,
    url_succes_client: str = "",
    url_annulation_client: str = "",
) -> TentativePaiement:
    """
    Renvoie le lien de paiement PayTech de la commande.
    Si une tentative est déjà en attente avec un lien valide, elle est réutilisée :
    le client ne peut pas ouvrir deux paiements en parallèle pour la même commande.
    """
    if commande.statut != StatutCommande.EN_ATTENTE_PAIEMENT:
        raise ErreurMetier(
            f"La commande {commande.reference} n'est plus en attente de paiement.",
            code="commande_deja_traitee",
        )
    if commande.tentatives_paiement.filter(statut=StatutPaiement.CONFIRME).exists():
        raise ErreurMetier("Cette commande est déjà payée.", code="commande_deja_payee")

    tentative_active = (
        commande.tentatives_paiement.filter(statut=StatutPaiement.EN_ATTENTE, montant_fcfa=commande.total_fcfa)
        .exclude(url_redirection="")
        .order_by("-date_creation")
        .first()
    )
    if tentative_active is not None:
        return tentative_active

    if not paytech_est_configure():
        logger.error("Clés PayTech absentes : impossible de créer un paiement.")
        raise ServiceExterneIndisponible("Le paiement en ligne n'est pas encore configuré. Contactez le support AYYOU.")

    # Toute ancienne tentative non aboutie est close : une seule tentative active par commande.
    commande.tentatives_paiement.filter(statut=StatutPaiement.EN_ATTENTE).update(statut=StatutPaiement.ANNULE)
    tentative = TentativePaiement.objects.create(
        commande=commande,
        montant_fcfa=commande.total_fcfa,
        environnement=settings.PAYTECH_ENVIRONNEMENT,
    )

    url_publique = settings.URL_PUBLIQUE_BACKEND.rstrip("/")
    if not url_publique.startswith("https://"):
        logger.warning("AYYOU_URL_PUBLIQUE_BACKEND n'est pas en HTTPS : PayTech ne pourra pas envoyer l'IPN.")
    url_succes = _construire_url_retour(url_succes_client, commande, "succes")
    url_annulation = _construire_url_retour(url_annulation_client, commande, "en_attente")

    payload = {
        "item_name": f"AYYOU - Commande {commande.reference}",
        "item_price": commande.total_fcfa,
        "currency": "XOF",
        "ref_command": tentative.reference_paiement,
        "command_name": f"Repas {commande.etablissement.nom} pour {commande.client.nom_complet}",
        "env": settings.PAYTECH_ENVIRONNEMENT,
        "ipn_url": f"{url_publique}/api/paiements/webhook-ipn/",
        "success_url": url_succes,
        "cancel_url": url_annulation,
        "custom_field": json.dumps({"commande_id": commande.id, "reference": commande.reference}),
    }

    try:
        reponse = requests.post(
            f"{settings.PAYTECH_URL_BASE.rstrip('/')}/payment/request-payment",
            json=payload,
            headers={**_en_tetes_paytech(), "Content-Type": "application/json"},
            timeout=settings.PAYTECH_DELAI_ATTENTE_SECONDES,
        )
        donnees = reponse.json()
    except (requests.RequestException, ValueError) as erreur:
        logger.error("Erreur réseau PayTech : %s", erreur)
        tentative.statut = StatutPaiement.ECHOUE
        tentative.save(update_fields=["statut"])
        raise ServiceExterneIndisponible("Le service de paiement PayTech est momentanément indisponible.")

    if reponse.status_code == 200 and donnees.get("success") == 1:
        tentative.token_paytech = donnees.get("token", "")
        tentative.url_redirection = donnees.get("redirect_url") or donnees.get("redirectUrl", "")
        tentative.save(update_fields=["token_paytech", "url_redirection"])
        return tentative

    message = donnees.get("message", "Échec de l'initialisation du paiement PayTech.")
    logger.error("Erreur API PayTech : %s (code %s)", message, reponse.status_code)
    tentative.statut = StatutPaiement.ECHOUE
    tentative.save(update_fields=["statut"])
    raise ErreurMetier(f"Échec de création du paiement : {message}", code="erreur_paytech")


def verifier_signature_paytech(donnees: dict) -> bool:
    """
    Vérifie que la notification vient bien de PayTech.
    Sans clés configurées, la réponse est toujours NON (aucune notification acceptée).
    """
    if not paytech_est_configure():
        logger.error("Notification PayTech refusée : clés PayTech non configurées.")
        return False

    cle_api = settings.PAYTECH_CLE_API
    cle_secrete = settings.PAYTECH_CLE_SECRETE

    hmac_recu = str(donnees.get("hmac_compute", ""))
    if hmac_recu:
        montant = donnees.get("final_item_price") or donnees.get("item_price", "")
        message = f"{montant}|{donnees.get('ref_command', '')}|{cle_api}"
        hmac_attendu = hmac.new(cle_secrete.encode(), message.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(hmac_attendu, hmac_recu):
            return True

    sha_cle_api = hashlib.sha256(cle_api.encode()).hexdigest()
    sha_cle_secrete = hashlib.sha256(cle_secrete.encode()).hexdigest()
    if hmac.compare_digest(sha_cle_api, str(donnees.get("api_key_sha256", ""))) and hmac.compare_digest(
        sha_cle_secrete, str(donnees.get("api_secret_sha256", ""))
    ):
        return True

    logger.warning("Signature de notification PayTech invalide.")
    return False


def _montant_notifie_est_correct(donnees: dict, tentative: TentativePaiement) -> bool:
    """Compare le prix notifié par PayTech au montant attendu de la tentative."""
    try:
        montant_recu = int(float(donnees.get("item_price")))
    except (TypeError, ValueError):
        return False
    return montant_recu == tentative.montant_fcfa


def _confirmer_tentative(tentative: TentativePaiement, commentaire: str) -> TentativePaiement:
    """
    Enregistre un paiement réussi et fait avancer la commande.
    Si la commande est déjà payée (double paiement) ou n'attend plus de paiement
    (annulée, expirée), l'argent reçu est rendu au client.
    """
    tentative.statut = StatutPaiement.CONFIRME
    tentative.date_confirmation = timezone.now()
    tentative.save(update_fields=["statut", "date_confirmation", "donnees_ipn"])

    commande = Commande.objects.select_for_update().get(pk=tentative.commande_id)
    autre_paiement = (
        TentativePaiement.objects.filter(commande=commande, statut__in=[StatutPaiement.CONFIRME, StatutPaiement.REMBOURSE])
        .exclude(pk=tentative.pk)
        .exists()
    )
    if autre_paiement or commande.statut != StatutCommande.EN_ATTENTE_PAIEMENT:
        logger.warning("Paiement %s reçu pour une commande déjà payée ou annulée : remboursement.", tentative.reference_paiement)
        rembourser_commande_paytech(tentative)
        return tentative

    transitionner_statut_commande(
        commande=commande,
        nouveau_statut=StatutCommande.CREEE_EN_ATTENTE,
        auteur=None,
        commentaire=commentaire,
    )
    return tentative


@transaction.atomic
def traiter_notification_ipn_paytech(donnees: dict) -> TentativePaiement:
    """Point d'entrée du webhook PayTech (idempotent : une notification répétée est ignorée)."""
    if not verifier_signature_paytech(donnees):
        raise ErreurMetier("Signature PayTech invalide.", code="signature_invalide")

    ref_command = donnees.get("ref_command")
    if not ref_command:
        raise ErreurMetier("Paramètre ref_command manquant.", code="ipn_incomplet")

    # Paiement d'abonnement d'un restaurant (référence « ABO-... ») : traité à part.
    if str(ref_command).startswith("ABO-"):
        from .abonnement import traiter_notification_abonnement

        return traiter_notification_abonnement(donnees)

    tentative = TentativePaiement.objects.select_for_update().filter(reference_paiement=ref_command).first()
    if tentative is None:
        raise ErreurMetier(f"Paiement introuvable pour ref_command={ref_command}.", code="paiement_introuvable")

    if tentative.statut in (StatutPaiement.CONFIRME, StatutPaiement.REMBOURSE):
        logger.info("Notification PayTech déjà traitée pour %s.", ref_command)
        return tentative

    tentative.donnees_ipn = donnees
    type_evenement = donnees.get("type_event", "")

    if type_evenement == "sale_complete":
        if not _montant_notifie_est_correct(donnees, tentative):
            logger.error("Montant PayTech incorrect pour %s : %s reçu, %s attendu.",
                         ref_command, donnees.get("item_price"), tentative.montant_fcfa)
            tentative.statut = StatutPaiement.ECHOUE
            tentative.save(update_fields=["statut", "donnees_ipn"])
            return tentative
        return _confirmer_tentative(tentative, "Paiement PayTech validé (notification IPN).")

    tentative.statut = StatutPaiement.ANNULE if type_evenement == "sale_canceled" else StatutPaiement.ECHOUE
    tentative.save(update_fields=["statut", "donnees_ipn"])
    logger.info("Paiement %s non abouti (%s).", ref_command, type_evenement)
    return tentative


def rembourser_commande_paytech(tentative: TentativePaiement) -> bool:
    """
    Demande le remboursement d'un paiement confirmé à PayTech.
    Renvoie True seulement si PayTech a réellement accepté le remboursement.
    En cas d'échec, la tentative reste CONFIRME : l'administration la voit « à rembourser ».
    """
    if tentative.statut != StatutPaiement.CONFIRME:
        raise ErreurMetier("Seul un paiement confirmé peut être remboursé.", code="remboursement_impossible")
    if not paytech_est_configure():
        logger.error("Remboursement impossible : clés PayTech non configurées.")
        return False

    try:
        reponse = requests.post(
            f"{settings.PAYTECH_URL_BASE.rstrip('/')}/payment/refund-payment",
            data={"ref_command": tentative.reference_paiement},
            headers=_en_tetes_paytech(),
            timeout=settings.PAYTECH_DELAI_ATTENTE_SECONDES,
        )
        donnees = reponse.json()
    except (requests.RequestException, ValueError) as erreur:
        logger.error("Erreur réseau lors du remboursement PayTech : %s", erreur)
        return False

    if reponse.status_code == 200 and donnees.get("success") == 1:
        tentative.statut = StatutPaiement.REMBOURSE
        tentative.reference_remboursement = str(donnees.get("refund_id", ""))
        tentative.save(update_fields=["statut", "reference_remboursement"])
        logger.info("Paiement %s remboursé.", tentative.reference_paiement)
        return True

    logger.error("PayTech a refusé le remboursement de %s : %s", tentative.reference_paiement, donnees.get("message"))
    return False


def rembourser_paiements_commande(commande: Commande) -> bool:
    """
    Rembourse tous les paiements confirmés d'une commande (refus, annulation, échec...).
    Renvoie True si plus rien n'est à rembourser.
    """
    tout_rembourse = True
    for tentative in commande.tentatives_paiement.filter(statut=StatutPaiement.CONFIRME):
        if not rembourser_commande_paytech(tentative):
            tout_rembourse = False
    return tout_rembourse


@transaction.atomic
def verifier_statut_paytech_en_ligne(commande_id: int) -> TentativePaiement:
    """
    Interroge PayTech sur la dernière tentative de la commande (notification en retard,
    client revenu de la page de paiement) et synchronise la commande.
    """
    tentative = (
        TentativePaiement.objects.select_for_update()
        .filter(commande_id=commande_id)
        .order_by("-date_creation")
        .first()
    )
    if tentative is None:
        raise ErreurMetier("Aucune tentative de paiement pour cette commande.", code="paiement_introuvable")
    if tentative.statut != StatutPaiement.EN_ATTENTE or not tentative.token_paytech or not paytech_est_configure():
        return tentative

    try:
        reponse = requests.get(
            f"{settings.PAYTECH_URL_BASE.rstrip('/')}/payment/get-status",
            params={"token_payment": tentative.token_paytech},
            headers=_en_tetes_paytech(),
            timeout=settings.PAYTECH_DELAI_ATTENTE_SECONDES,
        )
        paiement = reponse.json().get("payment", {}) if reponse.status_code == 200 else {}
    except (requests.RequestException, ValueError) as erreur:
        logger.warning("Impossible de vérifier le statut PayTech : %s", erreur)
        return tentative

    etat = str(paiement.get("state", "")).lower()
    if etat in ("completed", "success"):
        return _confirmer_tentative(tentative, "Paiement PayTech confirmé (vérification du statut).")
    if etat in ("canceled", "cancelled"):
        tentative.statut = StatutPaiement.ANNULE
        tentative.save(update_fields=["statut"])
    return tentative
