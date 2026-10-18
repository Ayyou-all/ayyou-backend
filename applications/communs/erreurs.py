"""
Erreurs métier communes et gestionnaire d'exceptions DRF.

Pourquoi ? Les services métier ne doivent pas dépendre de HTTP. Ils lèvent une
`ErreurMetier` (ex : « plat indisponible »), et le gestionnaire ci-dessous la
transforme en réponse JSON homogène pour le frontend :

    {"code": "plat_indisponible", "message": "Le plat ... n'est plus disponible.", "details": {...}}
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ErreurMetier(Exception):
    """Erreur prévue par une règle métier (statut HTTP 400 par défaut)."""

    statut_http = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, code: str = "erreur_metier", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class TransitionInterdite(ErreurMetier):
    """Changement de statut non autorisé par la machine à états (HTTP 409)."""

    statut_http = status.HTTP_409_CONFLICT

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="transition_interdite", details=details)


class AccesRefuse(ErreurMetier):
    """L'utilisateur n'a pas le droit d'agir sur cette ressource (HTTP 403)."""

    statut_http = status.HTTP_403_FORBIDDEN

    def __init__(self, message: str = "Action non autorisée pour votre compte."):
        super().__init__(message, code="acces_refuse")


class AbonnementRequis(ErreurMetier):
    """Restaurant suspendu : essai terminé et aucun abonnement actif (HTTP 403, code « abonnement_requis »)."""

    statut_http = status.HTTP_403_FORBIDDEN

    def __init__(self):
        super().__init__(
            "Votre période d'essai ou votre abonnement est terminé. Activez votre abonnement pour continuer.",
            code="abonnement_requis",
        )


class ServiceExterneIndisponible(ErreurMetier):
    """Un fournisseur externe (PayTech, service IA) ne répond pas (HTTP 503)."""

    statut_http = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self, message: str, code: str = "service_indisponible"):
        super().__init__(message, code=code)


def gestionnaire_exceptions(exception, contexte):
    """Branché dans REST_FRAMEWORK["EXCEPTION_HANDLER"]. Convertit ErreurMetier en JSON."""
    if isinstance(exception, ErreurMetier):
        return Response(
            {"code": exception.code, "message": exception.message, "details": exception.details},
            status=exception.statut_http,
        )
    return exception_handler(exception, contexte)
