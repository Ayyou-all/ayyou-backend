"""
Services métier pour l'envoi et la gestion des notifications AYYOU.
"""

from typing import Optional
from applications.utilisateurs.models import Utilisateur
from .models import Notification, TypeNotification


def creer_notification(
    destinataire: Utilisateur,
    titre: str,
    message: str,
    type_notification: str = TypeNotification.INFO_SYSTEME,
    texte_vocal: str = "",
    reference_commande: str = "",
) -> Notification:
    """Crée et enregistre une notification in-app/vocale pour un utilisateur."""
    return Notification.objects.create(
        destinataire=destinataire,
        titre=titre,
        message=message,
        type_notification=type_notification,
        texte_vocal=texte_vocal or titre,
        reference_commande=reference_commande,
    )


def marquer_notification_comme_lue(notification_id: int, utilisateur: Utilisateur) -> Optional[Notification]:
    """Marque une notification spécifique comme lue."""
    notif = Notification.objects.filter(pk=notification_id, destinataire=utilisateur).first()
    if notif and not notif.est_lue:
        notif.est_lue = True
        notif.save(update_fields=["est_lue"])
    return notif


def marquer_toutes_notifications_comme_lues(utilisateur: Utilisateur) -> int:
    """Marque l'ensemble des notifications d'un utilisateur comme lues."""
    return Notification.objects.filter(destinataire=utilisateur, est_lue=False).update(est_lue=True)


def compter_notifications_non_lues(utilisateur: Utilisateur) -> int:
    """Retourne le nombre de notifications en attente de lecture."""
    return Notification.objects.filter(destinataire=utilisateur, est_lue=False).count()


# ---------------------------------------------------------------------------
# Notifications automatiques à chaque changement de statut d'une commande
# ---------------------------------------------------------------------------

# Pour chaque nouveau statut : (destinataire, type, titre, message).
# Les textes utilisent {ref}, {restaurant}, {total}, {delai}, {livreur} et {motif}.
MESSAGES_PAR_STATUT = {
    "CREEE_EN_ATTENTE": [
        ("client", TypeNotification.COMMANDE_EN_PREPARATION, "Paiement confirmé",
         "Votre paiement de {total} FCFA est confirmé. {restaurant} doit maintenant accepter votre commande."),
        ("restaurant", TypeNotification.COMMANDE_NOUVELLE, "Nouvelle commande {ref}",
         "Nouvelle commande payée de {total} FCFA. Acceptez-la ou refusez-la rapidement."),
    ],
    "EN_PREPARATION": [
        ("client", TypeNotification.COMMANDE_EN_PREPARATION, "Commande acceptée",
         "{restaurant} prépare votre commande (environ {delai} min)."),
    ],
    "PRETE_POUR_RETRAIT": [
        ("client", TypeNotification.COMMANDE_PRETE, "Commande prête",
         "Votre commande est prête au restaurant. Nous cherchons un livreur."),
    ],
    "COURSE_ASSIGNEE": [
        ("client", TypeNotification.LIVREUR_ASSIGNE, "Livreur assigné",
         "{livreur} va récupérer votre commande chez {restaurant}."),
        ("restaurant", TypeNotification.LIVREUR_ASSIGNE, "Livreur assigné à {ref}",
         "{livreur} arrive pour récupérer la commande {ref}."),
    ],
    "EN_LIVRAISON": [
        ("client", TypeNotification.COMMANDE_EN_LIVRAISON, "Livreur en route",
         "Votre commande a été récupérée : {livreur} arrive chez vous."),
    ],
    "ARRIVE_CLIENT": [
        ("client", TypeNotification.LIVREUR_ARRIVE, "Votre livreur est arrivé",
         "{livreur} est à votre adresse. Donnez-lui votre code PIN pour recevoir la commande."),
    ],
    "LIVREE": [
        ("client", TypeNotification.COMMANDE_LIVREE, "Commande livrée", "Bon appétit ! Votre commande {ref} a été livrée."),
        ("restaurant", TypeNotification.COMMANDE_LIVREE, "Commande {ref} livrée", "La commande {ref} a été remise au client."),
    ],
    "REFUSEE_ANNULEE": [
        ("client", TypeNotification.COMMANDE_ANNULEE, "Commande {ref} annulée", "Votre commande a été annulée. Motif : {motif}"),
        ("restaurant", TypeNotification.COMMANDE_ANNULEE, "Commande {ref} annulée", "La commande {ref} a été annulée. Motif : {motif}"),
        ("livreur", TypeNotification.COMMANDE_ANNULEE, "Course {ref} annulée", "La course {ref} est annulée. Motif : {motif}"),
    ],
    "ECHEC_LIVRAISON": [
        ("client", TypeNotification.COMMANDE_ANNULEE, "Livraison impossible",
         "Votre commande {ref} n'a pas pu être livrée. Motif : {motif}. Le support AYYOU va vous contacter."),
        ("restaurant", TypeNotification.COMMANDE_ANNULEE, "Échec de livraison {ref}", "Motif : {motif}"),
        ("admins", TypeNotification.INFO_SYSTEME, "Échec de livraison {ref}", "À traiter par le support. Motif : {motif}"),
    ],
}


def administrateurs_actifs():
    return Utilisateur.objects.filter(role="ADMINISTRATEUR", is_active=True)


def _destinataires(commande, cible: str) -> list:
    if cible == "client":
        return [commande.client] if commande.client else []
    if cible == "restaurant":
        return [commande.etablissement.gerant] if commande.etablissement and commande.etablissement.gerant else []
    if cible == "livreur":
        livraison = getattr(commande, "livraison", None)
        return [livraison.livreur.utilisateur] if livraison else []
    if cible == "admins":
        return list(administrateurs_actifs())
    return []


def notifier_changement_statut(commande, nouveau_statut: str, auteur=None) -> None:
    """Prévient chaque acteur concerné du nouveau statut (jamais l'auteur de l'action lui-même)."""
    livraison = getattr(commande, "livraison", None)
    valeurs = {
        "ref": commande.reference,
        "restaurant": commande.etablissement.nom if commande.etablissement else "",
        "total": commande.total_fcfa,
        "delai": commande.delai_preparation_estime_minutes or "",
        "livreur": livraison.livreur.utilisateur.prenom if livraison else "Votre livreur",
        "motif": commande.motif_refus_ou_annulation or "non précisé",
    }
    for cible, type_notification, titre, message in MESSAGES_PAR_STATUT.get(nouveau_statut, []):
        for destinataire in _destinataires(commande, cible):
            if auteur is not None and destinataire.pk == auteur.pk:
                continue
            creer_notification(
                destinataire=destinataire,
                titre=titre.format(**valeurs),
                message=message.format(**valeurs),
                type_notification=type_notification,
                reference_commande=commande.reference,
            )
