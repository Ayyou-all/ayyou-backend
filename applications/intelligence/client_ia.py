"""
Client HTTP interne pour communiquer avec le microservice indépendant FastAPI AYYOU IA.

Prend en charge :
- L'injection de la clé d'autorisation interne `X-AYYOU-IA-KEY`
- Le timeout sécurisé (ne bloque pas le serveur Django)
- Le repli déterministe (fallback gracieux) si le microservice IA est injoignable
"""

import logging
from typing import Any, Dict, Optional
import httpx
from django.conf import settings

logger = logging.getLogger("ayyou.intelligence")


def appel_service_ia(point_de_terminaison: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Exécute un appel POST authentifié vers le microservice FastAPI.
    Renvoie le dictionnaire JSON de réponse ou None en cas d'échec / timeout.
    """
    url = f"{settings.SERVICE_IA_URL.rstrip('/')}/{point_de_terminaison.lstrip('/')}"
    en_tetes = {
        "X-AYYOU-IA-KEY": settings.SERVICE_IA_CLE_INTERNE,
        "Content-Type": "application/json",
    }
    delai = settings.SERVICE_IA_DELAI_ATTENTE_SECONDES

    try:
        with httpx.Client(timeout=delai) as client:
            reponse = client.post(url, json=payload, headers=en_tetes)
            if reponse.status_code == 200:
                return reponse.json()
            else:
                logger.warning(
                    "Le service IA a répondu avec le statut %s: %s",
                    reponse.status_code,
                    reponse.text,
                )
                return None
    except Exception as exc:
        logger.warning("Échec de connexion au microservice IA (%s): %s", url, exc)
        return None
