"""
Abonnement mensuel des restaurants (modèle économique AYYOU).

Règles :
1. Inscription du restaurant -> 14 jours d'essai gratuit (Etablissement.date_fin_essai).
2. Ensuite : 15 000 FCFA / mois, payés avec PayTech (Wave, Orange Money...).
3. L'abonnement n'est prolongé QUE lorsque PayTech confirme le paiement (notification signée,
   ou statut demandé directement à PayTech). Le retour du navigateur ne prouve rien.
4. Un renouvellement repart de la fin de l'accès en cours (essai ou abonnement) : aucun jour n'est perdu.
5. Sans essai ni abonnement valide, le restaurant est SUSPENDU : la gestion est bloquée par l'API
   (permission AbonnementValide) et il est masqué aux clients, mais ses données sont conservées.
6. Rappel 3 jours avant l'échéance et avis de suspension : une seule fois par échéance.

Le statut (ESSAI / ACTIF / SUSPENDU) est calculé à partir des dates : voir Etablissement.statut_abonnement.
"""

import calendar
import json
import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import ErreurMetier, ServiceExterneIndisponible
from applications.etablissements.models import Etablissement, StatutAbonnement, filtre_abonnement_valide
from applications.notifications.models import TypeNotification
from applications.notifications.services import administrateurs_actifs, creer_notification

from .models import PaiementAbonnement, StatutPaiement
from .services import _en_tetes_paytech, _montant_notifie_est_correct, _url_retour_https, paytech_est_configure

logger = logging.getLogger("ayyou.paiements")

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
# Nombre maximum de restaurants traités par passage (ne ralentit jamais une requête utilisateur)
LOT_MAXIMUM = 50
# Un lien de paiement PayTech déjà créé est réutilisé pendant ce délai (double clic, retour arrière)
DUREE_REUTILISATION_LIEN = timedelta(minutes=30)


# ---------------------------------------------------------------------------
# Petits outils
# ---------------------------------------------------------------------------
def ajouter_un_mois(date):
    """18 octobre -> 18 novembre ; 31 janvier -> 28 (ou 29) février."""
    mois = date.month % 12 + 1
    annee = date.year + (1 if date.month == 12 else 0)
    jour = min(date.day, calendar.monthrange(annee, mois)[1])
    return date.replace(year=annee, month=mois, day=jour)


def formater_date(date) -> str:
    """Ex : « 18 novembre 2026 »."""
    date = timezone.localtime(date)
    return f"{date.day} {MOIS[date.month - 1]} {date.year}"


def texte_jours(jours: int) -> str:
    """« demain », « dans 3 jours »..."""
    return "demain" if jours <= 1 else f"dans {jours} jours"


def resume_abonnement(etablissement: Etablissement) -> dict:
    """État de l'abonnement envoyé au frontend (le frontend n'invente rien, il affiche ceci)."""
    return {
        "statut": etablissement.statut_abonnement,
        "date_fin_essai": etablissement.date_fin_essai,
        "date_fin_abonnement": etablissement.date_fin_abonnement,
        "date_echeance": etablissement.date_echeance_abonnement,
        "jours_restants": etablissement.jours_restants_abonnement,
        "prix_fcfa": settings.PRIX_ABONNEMENT_RESTAURANT_FCFA,
    }


def resume_paiement(paiement: PaiementAbonnement) -> dict:
    return {
        "id": paiement.id,
        "reference": paiement.reference_paiement,
        "restaurant": paiement.etablissement.nom,
        "montant_fcfa": paiement.montant_fcfa,
        "statut": paiement.statut,
        "methode_paiement": paiement.methode_paiement,
        "date_creation": paiement.date_creation,
        "date_confirmation": paiement.date_confirmation,
        "date_debut_periode": paiement.date_debut_periode,
        "date_fin_periode": paiement.date_fin_periode,
    }


def _notifier_admins(titre: str, message: str) -> None:
    for admin in administrateurs_actifs():
        creer_notification(admin, titre, message, type_notification=TypeNotification.ABONNEMENT)


# ---------------------------------------------------------------------------
# Paiement PayTech
# ---------------------------------------------------------------------------
def initier_paiement_abonnement(etablissement: Etablissement) -> PaiementAbonnement:
    """Crée la demande de paiement PayTech (1 mois) et renvoie le paiement avec son lien de redirection."""
    prix = settings.PRIX_ABONNEMENT_RESTAURANT_FCFA

    lien_recent = (
        etablissement.paiements_abonnement.filter(
            statut=StatutPaiement.EN_ATTENTE,
            montant_fcfa=prix,
            date_creation__gte=timezone.now() - DUREE_REUTILISATION_LIEN,
        )
        .exclude(url_redirection="")
        .first()
    )
    if lien_recent is not None:
        return lien_recent

    if not paytech_est_configure():
        logger.error("Clés PayTech absentes : impossible de créer un paiement d'abonnement.")
        raise ServiceExterneIndisponible("Le paiement en ligne n'est pas encore configuré. Contactez le support AYYOU.")

    # Les anciennes demandes non payées sont closes (si PayTech confirme l'une d'elles plus tard, elle sera honorée).
    etablissement.paiements_abonnement.filter(statut=StatutPaiement.EN_ATTENTE).update(statut=StatutPaiement.ANNULE)
    paiement = PaiementAbonnement.objects.create(
        etablissement=etablissement, montant_fcfa=prix, environnement=settings.PAYTECH_ENVIRONNEMENT
    )

    url_page = f"{settings.URL_FRONTEND.rstrip('/')}/gerant/abonnement"
    payload = {
        "item_name": "AYYOU - Abonnement restaurant (1 mois)",
        "item_price": prix,
        "currency": "XOF",
        "ref_command": paiement.reference_paiement,
        "command_name": f"Abonnement mensuel AYYOU - {etablissement.nom}",
        "env": settings.PAYTECH_ENVIRONNEMENT,
        "ipn_url": f"{settings.URL_PUBLIQUE_BACKEND.rstrip('/')}/api/paiements/webhook-ipn/",
        "success_url": _url_retour_https(f"{url_page}?paiement=succes"),
        "cancel_url": _url_retour_https(f"{url_page}?paiement=annule"),
        "custom_field": json.dumps({"type": "abonnement", "etablissement_id": etablissement.id}),
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
        logger.error("Erreur réseau PayTech (abonnement) : %s", erreur)
        paiement.statut = StatutPaiement.ECHOUE
        paiement.save(update_fields=["statut"])
        raise ServiceExterneIndisponible("Le service de paiement PayTech est momentanément indisponible.")

    if reponse.status_code == 200 and donnees.get("success") == 1:
        paiement.token_paytech = donnees.get("token", "")
        paiement.url_redirection = donnees.get("redirect_url") or donnees.get("redirectUrl", "")
        paiement.save(update_fields=["token_paytech", "url_redirection"])
        return paiement

    message = donnees.get("message", "Échec de l'initialisation du paiement PayTech.")
    logger.error("Erreur API PayTech (abonnement) : %s (code %s)", message, reponse.status_code)
    paiement.statut = StatutPaiement.ECHOUE
    paiement.save(update_fields=["statut"])
    raise ErreurMetier(f"Échec de création du paiement : {message}", code="erreur_paytech")


def _activer_abonnement(paiement: PaiementAbonnement, methode_paiement: str = "") -> PaiementAbonnement:
    """Paiement confirmé par PayTech : enregistre la période achetée et prolonge l'accès du restaurant."""
    etablissement = Etablissement.objects.select_for_update().get(pk=paiement.etablissement_id)
    maintenant = timezone.now()
    deja_abonne = etablissement.paiements_abonnement.filter(statut=StatutPaiement.CONFIRME).exists()

    # Le nouveau mois commence à la fin de l'accès en cours (essai ou abonnement) : aucun jour n'est perdu.
    debut = max(maintenant, etablissement.date_echeance_abonnement or maintenant)
    fin = ajouter_un_mois(debut)

    paiement.statut = StatutPaiement.CONFIRME
    paiement.date_confirmation = maintenant
    paiement.date_debut_periode = debut
    paiement.date_fin_periode = fin
    paiement.methode_paiement = str(methode_paiement or "")[:40]
    paiement.save(update_fields=[
        "statut", "date_confirmation", "date_debut_periode", "date_fin_periode", "methode_paiement", "donnees_ipn"
    ])
    etablissement.date_fin_abonnement = fin
    etablissement.save(update_fields=["date_fin_abonnement"])

    creer_notification(
        etablissement.gerant,
        "Abonnement activé",
        f"Paiement de {paiement.montant_fcfa} FCFA confirmé. Votre abonnement est actif jusqu'au {formater_date(fin)}.",
        type_notification=TypeNotification.ABONNEMENT,
    )
    action = "a renouvelé son abonnement" if deja_abonne else "vient de souscrire à un abonnement"
    _notifier_admins(
        "Paiement d'abonnement confirmé",
        f"{etablissement.nom} {action} ({paiement.montant_fcfa} FCFA), actif jusqu'au {formater_date(fin)}.",
    )
    logger.info("Abonnement %s activé jusqu'au %s.", etablissement.nom, fin)
    return paiement


def traiter_notification_abonnement(donnees: dict) -> PaiementAbonnement:
    """
    Notification PayTech d'un paiement d'abonnement (référence « ABO-... »).
    Appelée par traiter_notification_ipn_paytech APRÈS vérification de la signature, dans sa transaction.
    Idempotente : une notification répétée ne prolonge jamais deux fois.
    """
    reference = donnees.get("ref_command")
    paiement = PaiementAbonnement.objects.select_for_update().filter(reference_paiement=reference).first()
    if paiement is None:
        raise ErreurMetier(f"Paiement d'abonnement introuvable pour ref_command={reference}.", code="paiement_introuvable")
    if paiement.statut == StatutPaiement.CONFIRME:
        logger.info("Notification PayTech déjà traitée pour %s.", reference)
        return paiement

    paiement.donnees_ipn = donnees
    type_evenement = donnees.get("type_event", "")
    if type_evenement == "sale_complete":
        if not _montant_notifie_est_correct(donnees, paiement):
            logger.error("Montant PayTech incorrect pour %s : %s reçu, %s attendu.",
                         reference, donnees.get("item_price"), paiement.montant_fcfa)
            paiement.statut = StatutPaiement.ECHOUE
            paiement.save(update_fields=["statut", "donnees_ipn"])
            return paiement
        return _activer_abonnement(paiement, donnees.get("payment_method", ""))

    paiement.statut = StatutPaiement.ANNULE if type_evenement == "sale_canceled" else StatutPaiement.ECHOUE
    paiement.save(update_fields=["statut", "donnees_ipn"])
    return paiement


@transaction.atomic
def verifier_paiement_abonnement(etablissement: Etablissement) -> PaiementAbonnement | None:
    """
    Retour de la page PayTech : on demande le statut réel à PayTech (la notification a peut-être du retard).
    Rien n'est activé sans confirmation de PayTech.
    """
    paiement = (
        PaiementAbonnement.objects.select_for_update()
        .filter(etablissement=etablissement, statut=StatutPaiement.EN_ATTENTE)
        .exclude(token_paytech="")
        .order_by("-date_creation")
        .first()
    )
    if paiement is None or not paytech_est_configure():
        return paiement

    try:
        reponse = requests.get(
            f"{settings.PAYTECH_URL_BASE.rstrip('/')}/payment/get-status",
            params={"token_payment": paiement.token_paytech},
            headers=_en_tetes_paytech(),
            timeout=settings.PAYTECH_DELAI_ATTENTE_SECONDES,
        )
        infos = reponse.json().get("payment", {}) if reponse.status_code == 200 else {}
    except (requests.RequestException, ValueError) as erreur:
        logger.warning("Impossible de vérifier le statut PayTech (abonnement) : %s", erreur)
        return paiement

    etat = str(infos.get("state", "")).lower()
    if etat in ("completed", "success"):
        return _activer_abonnement(paiement, infos.get("payment_method", ""))
    if etat in ("canceled", "cancelled"):
        paiement.statut = StatutPaiement.ANNULE
        paiement.save(update_fields=["statut"])
    return paiement


# ---------------------------------------------------------------------------
# Rappels (J-3) et suspensions : lancé par le mécanisme d'expiration existant
# (middleware au plus une fois par minute, ou `manage.py traiter_expirations`).
# ---------------------------------------------------------------------------
def traiter_echeances_abonnements() -> int:
    """Envoie les rappels et avis de suspension pas encore envoyés. Renvoie le nombre de notifications."""
    maintenant = timezone.now()
    limite_rappel = maintenant + timedelta(days=settings.RAPPEL_ABONNEMENT_JOURS_AVANT)
    restaurants = Etablissement.objects.exclude(statut_validation=StatutValidationPartenaire.BANNI).select_related("gerant")
    nombre = 0

    # 1. Rappel avant l'échéance (une fois par échéance : rappel_envoye_pour garde l'échéance déjà rappelée)
    pas_encore_rappele = (
        Q(rappel_envoye_pour__isnull=True)
        | Q(rappel_envoye_pour__lt=F("date_fin_essai"))
        | Q(rappel_envoye_pour__lt=F("date_fin_abonnement"))
    )
    proches = Q(date_fin_essai__gt=maintenant, date_fin_essai__lte=limite_rappel) | Q(
        date_fin_abonnement__gt=maintenant, date_fin_abonnement__lte=limite_rappel
    )
    for etablissement in restaurants.filter(proches).filter(pas_encore_rappele)[:LOT_MAXIMUM]:
        echeance = etablissement.date_echeance_abonnement
        if not (maintenant < echeance <= limite_rappel) or etablissement.rappel_envoye_pour == echeance:
            continue  # l'échéance réelle est plus loin (ex : essai bientôt fini mais abonnement déjà payé)
        quand = texte_jours(etablissement.jours_restants_abonnement)
        prix = settings.PRIX_ABONNEMENT_RESTAURANT_FCFA
        if etablissement.statut_abonnement == StatutAbonnement.ACTIF:
            creer_notification(
                etablissement.gerant,
                "Votre abonnement arrive à échéance",
                f"Votre abonnement expire {quand}. Pensez à le renouveler ({prix} FCFA / mois) "
                "pour continuer à utiliser votre espace restaurant.",
                type_notification=TypeNotification.ABONNEMENT,
            )
            _notifier_admins(
                "Un abonnement arrive à expiration",
                f"L'abonnement de {etablissement.nom} expire le {formater_date(echeance)}.",
            )
        else:
            creer_notification(
                etablissement.gerant,
                "Fin de votre essai gratuit",
                f"Votre période d'essai se termine {quand}. Abonnez-vous ({prix} FCFA / mois) "
                "pour continuer à utiliser votre espace restaurant.",
                type_notification=TypeNotification.ABONNEMENT,
            )
        etablissement.rappel_envoye_pour = echeance
        etablissement.save(update_fields=["rappel_envoye_pour"])
        nombre += 1

    # 2. Échéance dépassée : le restaurant est suspendu (calculé), on prévient une seule fois
    pas_encore_notifie = (
        Q(expiration_notifiee_pour__isnull=True)
        | Q(expiration_notifiee_pour__lt=F("date_fin_essai"))
        | Q(expiration_notifiee_pour__lt=F("date_fin_abonnement"))
    )
    for etablissement in restaurants.exclude(filtre_abonnement_valide()).filter(pas_encore_notifie)[:LOT_MAXIMUM]:
        echeance = etablissement.date_echeance_abonnement
        if echeance is None or etablissement.expiration_notifiee_pour == echeance:
            continue
        if etablissement.date_fin_abonnement:
            titre_gerant, debut_message = "Votre abonnement a expiré", "Votre abonnement a expiré."
            titre_admin = "Un abonnement a expiré"
        else:
            titre_gerant, debut_message = "Votre période d'essai est terminée", "Votre période d'essai est terminée."
            titre_admin = "Fin d'essai sans abonnement"
        creer_notification(
            etablissement.gerant,
            titre_gerant,
            f"{debut_message} Votre espace restaurant est suspendu : activez votre abonnement "
            f"({settings.PRIX_ABONNEMENT_RESTAURANT_FCFA} FCFA / mois) pour le réactiver. Vos données sont conservées.",
            type_notification=TypeNotification.ABONNEMENT,
        )
        _notifier_admins(titre_admin, f"{etablissement.nom} est passé en statut suspendu (abonnement requis).")
        etablissement.expiration_notifiee_pour = echeance
        etablissement.save(update_fields=["expiration_notifiee_pour"])
        nombre += 1
    return nombre


# ---------------------------------------------------------------------------
# Statistiques administrateur (uniquement des paiements CONFIRMÉS)
# ---------------------------------------------------------------------------
def filtre_statut_abonnement(statut: str) -> Q:
    """Filtre SQL équivalent à Etablissement.statut_abonnement."""
    maintenant = timezone.now()
    actif = Q(date_fin_abonnement__gt=maintenant)
    if statut == StatutAbonnement.ACTIF:
        return actif
    if statut == StatutAbonnement.ESSAI:
        return ~actif & Q(date_fin_essai__gt=maintenant)
    return ~filtre_abonnement_valide()


def statistiques_abonnements() -> dict:
    maintenant = timezone.localtime()
    debut_jour = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
    debut_semaine = debut_jour - timedelta(days=debut_jour.weekday())
    debut_mois = debut_jour.replace(day=1)
    debut_annee = debut_mois.replace(month=1)

    restaurants = Etablissement.objects.all()
    confirmes = PaiementAbonnement.objects.filter(statut=StatutPaiement.CONFIRME)

    def revenus_depuis(debut) -> int:
        return confirmes.filter(date_confirmation__gte=debut).aggregate(total=Sum("montant_fcfa"))["total"] or 0

    abonnes = restaurants.filter(filtre_statut_abonnement(StatutAbonnement.ACTIF)).count()
    cumul = confirmes.aggregate(total=Sum("montant_fcfa"), nombre=Count("id"), moyenne=Avg("montant_fcfa"))
    return {
        "prix_fcfa": settings.PRIX_ABONNEMENT_RESTAURANT_FCFA,
        "total_restaurants": restaurants.count(),
        "en_essai": restaurants.filter(filtre_statut_abonnement(StatutAbonnement.ESSAI)).count(),
        "abonnes": abonnes,
        "suspendus": restaurants.filter(filtre_statut_abonnement(StatutAbonnement.SUSPENDU)).count(),
        "abonnements_actifs": abonnes,
        # Restaurants qui ont déjà payé mais dont l'abonnement est terminé
        "abonnements_expires": restaurants.filter(date_fin_abonnement__lte=timezone.now()).count(),
        "nombre_paiements": cumul["nombre"],
        "revenus_aujourd_hui": revenus_depuis(debut_jour),
        "revenus_semaine": revenus_depuis(debut_semaine),
        "revenus_mois": revenus_depuis(debut_mois),
        "revenus_annee": revenus_depuis(debut_annee),
        "revenus_cumules": cumul["total"] or 0,
        "montant_moyen": round(cumul["moyenne"] or 0),
    }
