"""
Services du domaine Paiement pour AYYOU (Intégration officielle PayTech Sénégal).

Documentation officielle :
- Endpoint Demande : POST https://paytech.sn/api/payment/request-payment
- Endpoint Statut : GET https://paytech.sn/api/payment/get-status?token_payment=...
- Endpoint Remboursement : POST https://paytech.sn/api/payment/refund-payment
- Webhook IPN :
    - Événement de succès : type_event == "sale_complete"
    - Validation HMAC (recommandée) : HMAC-SHA256(item_price|ref_command|API_KEY, secret=API_SECRET) == hmac_compute
    - Validation Hash classique : SHA256(API_KEY) == api_key_sha256 et SHA256(API_SECRET) == api_secret_sha256
"""

import hashlib
import hmac
import logging
import json
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from applications.commandes.models import Commande, StatutCommande
from applications.commandes.services import transitionner_statut_commande
from applications.communs.erreurs import ErreurMetier, ServiceExterneIndisponible

from .models import StatutPaiement, TentativePaiement

logger = logging.getLogger("ayyou.paiements")


def initier_demande_paiement_paytech(
    commande: Commande,
    url_succes_client: str = "",
    url_annulation_client: str = "",
) -> TentativePaiement:
    """
    Crée une tentative de paiement interne et contacte l'API PayTech pour générer le lien de paiement.
    """
    if commande.statut != StatutCommande.EN_ATTENTE_PAIEMENT:
        raise ErreurMetier(
            f"La commande {commande.reference} n'est pas en attente de paiement (statut actuel : {commande.statut}).",
            code="commande_deja_traitee",
        )

    # Référence unique interne passée à PayTech
    tentative = TentativePaiement.objects.create(
        commande=commande,
        montant_fcfa=commande.total_fcfa,
        environnement=settings.PAYTECH_ENVIRONNEMENT,
    )

    cle_api = settings.PAYTECH_CLE_API
    cle_secrete = settings.PAYTECH_CLE_SECRETE
    url_base = settings.PAYTECH_URL_BASE.rstrip("/")

    # URL IPN de rappel (Webhook) appelée par les serveurs PayTech (PayTech exige impérativement HTTPS)
    base_pub = settings.URL_PUBLIQUE_BACKEND.rstrip("/")
    if not base_pub.startswith("https://"):
        ipn_url = "https://api.ayyou.sn/api/paiements/webhook-ipn/"
    else:
        ipn_url = f"{base_pub}/api/paiements/webhook-ipn/"

    # PayTech et Wave (Intech API) exigent impérativement des URLs valides en HTTPS.
    # Si le frontend est en local (ex: http://localhost:4200), Wave rejette le paiement avec :
    # "successRedirectUrl doit être un URL".
    # On garantit donc des URLs HTTPS complètes et conformes.
    if url_succes_client and url_succes_client.startswith("https://") and "localhost" not in url_succes_client and "127.0.0.1" not in url_succes_client:
        success_url = url_succes_client
    else:
        success_url = f"https://ayyou.sn/commandes/suivi/{commande.id}"

    if url_annulation_client and url_annulation_client.startswith("https://") and "localhost" not in url_annulation_client and "127.0.0.1" not in url_annulation_client:
        cancel_url = url_annulation_client
    else:
        cancel_url = f"https://ayyou.sn/commandes/suivi/{commande.id}?paiement=en_attente"

    payload = {
        "item_name": f"AYYOU - Commande {commande.reference}",
        "item_price": commande.total_fcfa,
        "currency": "XOF",
        "ref_command": tentative.reference_paiement,
        "command_name": f"Repas {commande.etablissement.nom} pour {commande.client.nom_complet}",
        "env": settings.PAYTECH_ENVIRONNEMENT,
        "ipn_url": ipn_url,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "successRedirectUrl": success_url,
        "errorRedirectUrl": cancel_url,
        "custom_field": json.dumps({"commande_id": commande.id, "reference": commande.reference}),
    }

    headers = {
        "API_KEY": cle_api,
        "API_SECRET": cle_secrete,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Si les clés réelles ne sont pas encore renseignées dans le .env, simuler une réponse sandbox pour dev
    if not cle_api or not cle_secrete:
        logger.warning("Clés PayTech absentes dans la configuration : simulation locale de redirection.")
        tentative.token_paytech = f"token_dev_{tentative.id}"
        tentative.url_redirection = f"https://paytech.sn/payment/checkout/{tentative.token_paytech}"
        tentative.save(update_fields=["token_paytech", "url_redirection"])
        return tentative

    endpoint_request = f"{url_base}/payment/request-payment"

    try:
        reponse = requests.post(
            endpoint_request,
            json=payload,
            headers=headers,
            timeout=settings.PAYTECH_DELAI_ATTENTE_SECONDES,
        )
        reponse_json = reponse.json()
    except requests.RequestException as e:
        logger.error(f"Erreur réseau lors de l'appel PayTech : {e}")
        raise ServiceExterneIndisponible("Le service de paiement PayTech est momentanément indisponible.")

    if reponse.status_code == 200 and reponse_json.get("success") == 1:
        token = reponse_json.get("token", "")
        # PayTech fournit parfois "redirect_url" ou "redirectUrl"
        redirect_url = reponse_json.get("redirect_url") or reponse_json.get("redirectUrl", "")

        tentative.token_paytech = token
        tentative.url_redirection = redirect_url
        tentative.save(update_fields=["token_paytech", "url_redirection"])
        return tentative
    else:
        message_erreur = reponse_json.get("message", "Échec de l'initialisation du paiement PayTech.")
        logger.error(f"Erreur API PayTech : {message_erreur} (code {reponse.status_code})")
        tentative.statut = StatutPaiement.ECHOUE
        tentative.save(update_fields=["statut"])
        raise ErreurMetier(f"Échec de création du paiement : {message_erreur}", code="erreur_paytech")


def verifier_signature_paytech(donnees: dict) -> bool:
    """
    Vérifie l'authenticité de la notification IPN selon la documentation PayTech.
    Prend en charge :
    1. La méthode HMAC-SHA256 (recommandée) via `hmac_compute`.
    2. La méthode de hachage SHA256 des clés d'API.
    """
    cle_api = settings.PAYTECH_CLE_API
    cle_secrete = settings.PAYTECH_CLE_SECRETE

    # En environnement de test / développement sans clés configurées
    if not cle_api or not cle_secrete:
        return True

    # 1. Vérification par HMAC si fourni
    if "hmac_compute" in donnees:
        hmac_recu = donnees.get("hmac_compute", "")
        montant = donnees.get("final_item_price") or donnees.get("item_price", "")
        ref_command = donnees.get("ref_command", "")

        message = f"{montant}|{ref_command}|{cle_api}"
        hmac_calcule = hmac.new(
            cle_secrete.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(hmac_calcule, hmac_recu):
            return True

    # 2. Vérification par SHA256 des clés API (méthode classique PayTech)
    sha_api_key_recu = donnees.get("api_key_sha256", "")
    sha_api_secret_recu = donnees.get("api_secret_sha256", "")

    sha_api_key_attendu = hashlib.sha256(cle_api.encode("utf-8")).hexdigest()
    sha_api_secret_attendu = hashlib.sha256(cle_secrete.encode("utf-8")).hexdigest()

    if hmac.compare_digest(sha_api_key_attendu, sha_api_key_recu) and hmac.compare_digest(
        sha_api_secret_attendu, sha_api_secret_recu
    ):
        return True

    logger.warning("Échec de vérification cryptographique de l'IPN PayTech.")
    return False


@transaction.atomic
def traiter_notification_ipn_paytech(donnees: dict) -> TentativePaiement:
    """
    Point d'entrée du webhook IPN PayTech.
    Gère l'idempotence, met à jour le statut du paiement et fait évoluer la commande.
    """
    # 1. Vérification de l'authenticité de la requête
    if not verifier_signature_paytech(donnees):
        raise ErreurMetier("Signature cryptographique PayTech invalide.", code="signature_invalide")

    ref_command = donnees.get("ref_command")
    if not ref_command:
        raise ErreurMetier("Paramètre ref_command manquant dans l'IPN.", code="ipn_incomplet")

    tentative = (
        TentativePaiement.objects.select_for_update()
        .filter(reference_paiement=ref_command)
        .select_related("commande")
        .first()
    )

    if tentative is None:
        raise ErreurMetier(f"Tentative de paiement introuvable pour ref_command={ref_command}", code="paiement_introuvable")

    # 2. Gestion de l'idempotence : si déjà confirmé, on ignore sans répéter l'action
    if tentative.statut == StatutPaiement.CONFIRME:
        logger.info(f"Notification IPN PayTech déjà traitée pour {ref_command} (idempotence).")
        return tentative

    type_event = donnees.get("type_event", "")
    tentative.donnees_ipn = donnees

    if type_event == "sale_complete":
        tentative.statut = StatutPaiement.CONFIRME
        tentative.date_confirmation = timezone.now()
        tentative.save(update_fields=["statut", "date_confirmation", "donnees_ipn"])

        # Faire évoluer la commande vers CREEE_EN_ATTENTE (prête pour acceptation restaurant)
        if tentative.commande.statut == StatutCommande.EN_ATTENTE_PAIEMENT:
            transitionner_statut_commande(
                commande=tentative.commande,
                nouveau_statut=StatutCommande.CREEE_EN_ATTENTE,
                auteur=None,
                commentaire="Paiement mobile PayTech validé avec succès via webhook IPN.",
            )
        logger.info(f"Paiement validé avec succès pour la commande {tentative.commande.reference}.")

    elif type_event == "sale_canceled":
        tentative.statut = StatutPaiement.ANNULE
        tentative.save(update_fields=["statut", "donnees_ipn"])
        logger.info(f"Paiement annulé par l'utilisateur pour {ref_command}.")

    else:
        tentative.statut = StatutPaiement.ECHOUE
        tentative.save(update_fields=["statut", "donnees_ipn"])
        logger.warning(f"Événement IPN non abouti : {type_event} pour {ref_command}.")

    return tentative


def rembourser_commande_paytech(tentative: TentativePaiement) -> bool:
    """
    Appelle l'API officielle de remboursement PayTech (POST /payment/refund-payment).
    """
    if tentative.statut != StatutPaiement.CONFIRME:
        raise ErreurMetier("Seul un paiement confirmé peut être remboursé.", code="remboursement_impossible")

    url_base = settings.PAYTECH_URL_BASE.rstrip("/")
    endpoint = f"{url_base}/payment/refund-payment"

    headers = {
        "API_KEY": settings.PAYTECH_CLE_API,
        "API_SECRET": settings.PAYTECH_CLE_SECRETE,
    }

    payload = {"ref_command": tentative.reference_paiement}

    try:
        reponse = requests.post(endpoint, data=payload, headers=headers, timeout=15)
        reponse_json = reponse.json()
    except requests.RequestException as e:
        logger.error(f"Erreur réseau remboursement PayTech : {e}")
        return False

    if reponse.status_code == 200 and reponse_json.get("success") == 1:
        tentative.statut = StatutPaiement.REMBOURSE
        tentative.reference_remboursement = str(reponse_json.get("refund_id", "REFUND_OK"))
        tentative.save(update_fields=["statut", "reference_remboursement"])
        return True

    return False


def verifier_statut_paytech_en_ligne(commande_id: int) -> TentativePaiement:
    """
    Vérifie l'état réel de la transaction auprès de l'API PayTech
    (GET https://paytech.sn/api/payment/get-status?token_payment=...)
    et synchronise le statut de la commande interne vers CREEE_EN_ATTENTE.
    """
    tentative = TentativePaiement.objects.filter(commande_id=commande_id).order_by("-date_creation").first()
    if not tentative:
        raise ErreurMetier("Aucune tentative de paiement pour cette commande.", code="paiement_introuvable")

    if tentative.statut == StatutPaiement.CONFIRME:
        return tentative

    if tentative.token_paytech and settings.PAYTECH_CLE_API and settings.PAYTECH_CLE_SECRETE:
        url_base = settings.PAYTECH_URL_BASE.rstrip("/")
        try:
            res = requests.get(
                f"{url_base}/payment/get-status",
                params={"token_payment": tentative.token_paytech},
                headers={
                    "API_KEY": settings.PAYTECH_CLE_API,
                    "API_SECRET": settings.PAYTECH_CLE_SECRETE,
                    "Accept": "application/json",
                },
                timeout=settings.PAYTECH_DELAI_ATTENTE_SECONDES,
            )
            if res.status_code == 200:
                data = res.json()
                payment = data.get("payment", {})
                state = str(payment.get("state", "")).lower()
                # Si payé ou si en environnement de test après retour du guichet
                if state in ["completed", "success"] or (settings.PAYTECH_ENVIRONNEMENT == "test" and state != "canceled"):
                    tentative.statut = StatutPaiement.CONFIRME
                    tentative.date_confirmation = timezone.now()
                    tentative.save(update_fields=["statut", "date_confirmation"])

                    if tentative.commande.statut == StatutCommande.EN_ATTENTE_PAIEMENT:
                        transitionner_statut_commande(
                            commande=tentative.commande,
                            nouveau_statut=StatutCommande.CREEE_EN_ATTENTE,
                            auteur=None,
                            commentaire="Paiement mobile PayTech confirmé avec succès.",
                        )
                    return tentative
        except Exception as e:
            logger.warning(f"Impossible de vérifier le statut PayTech en ligne : {e}")

    # Fallback pour environnement de test PayTech
    if settings.PAYTECH_ENVIRONNEMENT == "test" and tentative.commande.statut == StatutCommande.EN_ATTENTE_PAIEMENT:
        tentative.statut = StatutPaiement.CONFIRME
        tentative.date_confirmation = timezone.now()
        tentative.save(update_fields=["statut", "date_confirmation"])
        transitionner_statut_commande(
            commande=tentative.commande,
            nouveau_statut=StatutCommande.CREEE_EN_ATTENTE,
            auteur=None,
            commentaire="Paiement PayTech validé (environnement de test).",
        )

    return tentative
