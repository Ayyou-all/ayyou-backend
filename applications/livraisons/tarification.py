"""
Module de tarification kilométrique et de contrôle d'éligibilité géographique pour AYYOU.
Région desservie : Région de Dakar (Dakar, Guédiawaye, Pikine, Rufisque, Keur Massar).
"""

import math
from applications.communs.erreurs import ErreurMetier

# Bounding box englobant toute la région de Dakar (presqu'île et banlieue jusqu'à Diamniadio/Sangalkam)
DAKAR_LAT_MIN = 14.600000
DAKAR_LAT_MAX = 14.900000
DAKAR_LNG_MIN = -17.550000
DAKAR_LNG_MAX = -17.080000

MESSAGE_ZONE_NON_ELIGIBLE = (
    "Nous sommes désolés, cette zone n'est pas encore éligible à la livraison AYYOU. "
    "Notre équipe travaille à l'extension de nos activités vers d'autres régions du Sénégal et d'autres pays. "
    "Merci pour votre compréhension."
)


def est_dans_zone_dakar(latitude: float, longitude: float) -> bool:
    """Vérifie si les coordonnées se situent dans la région de Dakar éligible."""
    try:
        lat = float(latitude)
        lng = float(longitude)
        return (DAKAR_LAT_MIN <= lat <= DAKAR_LAT_MAX) and (DAKAR_LNG_MIN <= lng <= DAKAR_LNG_MAX)
    except (TypeError, ValueError):
        return False


def valider_eligibilite_zone_livraison(latitude, longitude):
    """
    Vérifie l'éligibilité géographique de l'adresse de livraison.
    Si les coordonnées fournies sont en dehors de la région de Dakar,
    lève l'exception métier avec le message d'indisponibilité requis.
    """
    if latitude is not None and longitude is not None:
        try:
            lat = float(latitude)
            lng = float(longitude)
            if abs(lat) > 0.001 or abs(lng) > 0.001:
                if not est_dans_zone_dakar(lat, lng):
                    raise ErreurMetier(
                        MESSAGE_ZONE_NON_ELIGIBLE,
                        code="zone_non_eligible",
                    )
        except (ValueError, TypeError):
            pass


def calculer_distance_orthodromique_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcul de distance Haversine en kilomètres."""
    r = 6371.0  # Rayon moyen de la Terre en kilomètres
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(r * c, 2)


def calculer_frais_livraison_progressifs(
    distance_km: float,
    frais_base: int = 500,
) -> int:
    """
    Grille tarifaire progressive AYYOU :
    - Forfait de base : 500 FCFA
    - 0 à 2 km : 100 FCFA / km
    - 2 à 5 km : 100 FCFA / km
    - 5 à 10 km : 125 FCFA / km
    - 10 à 15 km : 150 FCFA / km
    - 15 à 20 km : 175 FCFA / km
    - > 20 km : Zone non éligible (distance excessive)
    """
    if distance_km > 20.0:
        raise ErreurMetier(
            MESSAGE_ZONE_NON_ELIGIBLE,
            code="zone_non_eligible",
            details={"distance_km": distance_km},
        )

    frais = float(frais_base)
    reste = max(0.0, distance_km)

    # 0 à 2 km : 100 FCFA / km
    tranche_2 = min(reste, 2.0)
    frais += tranche_2 * 100.0
    reste -= tranche_2

    # 2 à 5 km : 100 FCFA / km
    if reste > 0:
        tranche_5 = min(reste, 3.0)
        frais += tranche_5 * 100.0
        reste -= tranche_5

    # 5 à 10 km : 125 FCFA / km
    if reste > 0:
        tranche_10 = min(reste, 5.0)
        frais += tranche_10 * 125.0
        reste -= tranche_10

    # 10 à 15 km : 150 FCFA / km
    if reste > 0:
        tranche_15 = min(reste, 5.0)
        frais += tranche_15 * 150.0
        reste -= tranche_15

    # 15 à 20 km : 175 FCFA / km
    if reste > 0:
        tranche_20 = min(reste, 5.0)
        frais += tranche_20 * 175.0

    # Arrondi aux 50 FCFA supérieurs pour faciliter les paiements en espèces/Wave
    frais_entier = int(math.ceil(frais / 50.0) * 50)
    return max(500, frais_entier)


def calculer_gain_livreur(frais_livraison_fcfa: int) -> int:
    """
    Gain du livreur = pourcentage configurable des frais de livraison payés par le client.
    Le gain ne dépasse jamais les frais encaissés : la plateforme ne perd pas d'argent sur une course.
    """
    from django.conf import settings

    pourcentage = settings.PART_LIVREUR_FRAIS_LIVRAISON_POURCENT
    gain = int(frais_livraison_fcfa * pourcentage / 100)
    return min(gain, frais_livraison_fcfa)


def calculer_frais_livraison_commande(etablissement, lat_client, lng_client) -> int:
    """
    Calcule le montant des frais de livraison pour une commande.
    Vérifie l'éligibilité de la zone de livraison et applique la grille kilométrique.
    """
    valider_eligibilite_zone_livraison(lat_client, lng_client)

    if (
        etablissement.latitude is not None
        and etablissement.longitude is not None
        and lat_client is not None
        and lng_client is not None
    ):
        try:
            distance = calculer_distance_orthodromique_km(
                etablissement.latitude,
                etablissement.longitude,
                lat_client,
                lng_client,
            )
            return calculer_frais_livraison_progressifs(distance)
        except ErreurMetier:
            raise
        except Exception:
            pass

    return etablissement.frais_livraison_fcfa or 1000
