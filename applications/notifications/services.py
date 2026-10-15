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
