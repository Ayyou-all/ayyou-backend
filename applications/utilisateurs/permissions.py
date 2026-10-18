"""
Permissions par rôle, réutilisées par toutes les applications.

Rappel : les gardes Angular ne protègent rien côté serveur. Chaque vue DRF
déclare ici ses rôles autorisés. Les vérifications d'appartenance (« ce plat
est-il à MON restaurant ? ») sont faites dans les requêtes (queryset filtré)
ou dans les services.

`has_permission` est un nom imposé par Django REST Framework.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from applications.communs.erreurs import AbonnementRequis

from .models import ROLES_GERANTS, Role


class _PermissionParRole(BasePermission):
    roles_autorises: set = set()
    message = "Votre rôle ne permet pas d'accéder à cette ressource."

    def has_permission(self, request, view):
        utilisateur = request.user
        return bool(utilisateur and utilisateur.is_authenticated and utilisateur.role in self.roles_autorises)


class EstClient(_PermissionParRole):
    roles_autorises = {Role.CLIENT}


class EstGerantEtablissement(_PermissionParRole):
    """Gérant de restaurant qui gère son établissement."""

    roles_autorises = set(ROLES_GERANTS)


class EstLivreur(_PermissionParRole):
    roles_autorises = {Role.LIVREUR}


class EstAdministrateur(_PermissionParRole):
    roles_autorises = {Role.ADMINISTRATEUR}


class EstPartenaire(_PermissionParRole):
    """Restaurant ou Livreur (comptes soumis à validation)."""

    roles_autorises = {Role.RESTAURANT, Role.LIVREUR}


class AbonnementValide(BasePermission):
    """
    À ajouter APRÈS EstGerantEtablissement sur les vues de gestion du restaurant.
    Le restaurant doit être en essai gratuit ou avoir un abonnement non expiré,
    sinon l'API répond 403 avec le code « abonnement_requis » (impossible de contourner par l'API).
    """

    # Mettre à True pour laisser la simple consultation (GET) à un restaurant suspendu.
    lecture_autorisee = False

    def has_permission(self, request, view):
        if self.lecture_autorisee and request.method in SAFE_METHODS:
            return True
        etablissement = getattr(request.user, "etablissement", None)
        if etablissement is not None and not etablissement.abonnement_valide:
            raise AbonnementRequis()
        return True


class AbonnementValidePourModifier(AbonnementValide):
    """Suspendu : peut consulter (GET) mais pas modifier."""

    lecture_autorisee = True
