"""
Configuration principale du backend AYYOU.

Toutes les valeurs sensibles ou dépendantes de l'environnement sont lues depuis
des variables d'environnement (fichier `.env` en local, voir `.env.example`).
Les noms des réglages Django (DEBUG, DATABASES, ...) sont imposés par Django
et ne sont donc pas traduits.
"""

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def lire_booleen(nom_variable: str, valeur_par_defaut: bool = False) -> bool:
    """Lit une variable d'environnement booléenne ("1", "true", "oui" => True)."""
    valeur = os.getenv(nom_variable)
    if valeur is None:
        return valeur_par_defaut
    return valeur.strip().lower() in {"1", "true", "oui", "yes"}


def lire_liste(nom_variable: str, valeur_par_defaut: str = "") -> list[str]:
    """Lit une liste séparée par des virgules."""
    return [element.strip() for element in os.getenv(nom_variable, valeur_par_defaut).split(",") if element.strip()]


# --- Sécurité -----------------------------------------------------------------
DEBUG = lire_booleen("AYYOU_DEBUG", True)
SECRET_KEY = os.getenv("AYYOU_CLE_SECRETE_DJANGO", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("AYYOU_CLE_SECRETE_DJANGO est obligatoire hors mode développement.")
    # Clé de développement uniquement : elle change à chaque installation si .env est absent.
    SECRET_KEY = "cle-developpement-non-securisee-a-remplacer"

ALLOWED_HOSTS = ["*"] if DEBUG else lire_liste("AYYOU_HOTES_AUTORISES", "api.ayyou.site,ayyou.site,localhost,127.0.0.1,backend")

# --- Applications -------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Bibliothèques tierces
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    # Applications métier AYYOU
    "applications.utilisateurs",
    "applications.authentification",
    "applications.etablissements",
    "applications.catalogue",
    "applications.panier",
    "applications.publications",
    "applications.commandes",
    "applications.paiements",
    "applications.livraisons",
    "applications.abonnements",
    "applications.notifications",
    "applications.intelligence",
    "applications.administration",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Base de données ----------------------------------------------------------
# Support prioritaire de DATABASE_URL (format: postgresql://USER:PASS@HOST:PORT/DBNAME)
# Si DATABASE_URL est absent : SQLite par défaut (idéal pour le développement local).
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    url_bdd = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": url_bdd.path.lstrip("/"),
            "USER": unquote(url_bdd.username or ""),
            "PASSWORD": unquote(url_bdd.password or ""),
            "HOST": url_bdd.hostname or "localhost",
            "PORT": str(url_bdd.port or 5432),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    MOTEUR_BDD = (os.getenv("AYYOU_MOTEUR_BDD") or os.getenv("DB_ENGINE") or "sqlite").strip().lower()

    if MOTEUR_BDD in ("postgresql", "postgres", "psql"):
        _nom_bdd = os.getenv("AYYOU_BDD_NOM") or os.getenv("POSTGRES_DB") or os.getenv("DB_NAME", "ayyou")
        _user_bdd = os.getenv("AYYOU_BDD_UTILISATEUR") or os.getenv("POSTGRES_USER") or os.getenv("DB_USER", "ayyou")
        _pass_bdd = os.getenv("AYYOU_BDD_MOT_DE_PASSE") or os.getenv("POSTGRES_PASSWORD") or os.getenv("DB_PASSWORD", "")
        _hote_bdd = os.getenv("AYYOU_BDD_HOTE") or os.getenv("POSTGRES_HOST") or os.getenv("DB_HOST", "localhost")
        _port_bdd = os.getenv("AYYOU_BDD_PORT") or os.getenv("POSTGRES_PORT") or os.getenv("DB_PORT", "5432")

        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": _nom_bdd,
                "USER": _user_bdd,
                "PASSWORD": _pass_bdd,
                "HOST": _hote_bdd,
                "PORT": _port_bdd,
                "CONN_MAX_AGE": 60,
            }
        }
    else:
        fichier_bdd = os.getenv("AYYOU_BDD_FICHIER_SQLITE")
        if not fichier_bdd:
            fichier_bdd = "data/db.sqlite3" if (BASE_DIR / "data").is_dir() else "db.sqlite3"
        chemin_bdd = BASE_DIR / fichier_bdd
        chemin_bdd.parent.mkdir(parents=True, exist_ok=True)
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": chemin_bdd,
            }
        }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Utilisateur personnalisé -------------------------------------------------
AUTH_USER_MODEL = "utilisateurs.Utilisateur"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

# --- Internationalisation -----------------------------------------------------
LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Dakar"
USE_I18N = True
USE_TZ = True

# --- Fichiers statiques et médias ---------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/medias/"
MEDIA_ROOT = BASE_DIR / os.getenv("AYYOU_DOSSIER_MEDIAS", "medias")

# Limites de téléversement (en octets) — la vidéo est limitée en durée ET en taille.
TAILLE_MAX_PHOTO_OCTETS = int(os.getenv("AYYOU_TAILLE_MAX_PHOTO_MO", "8")) * 1024 * 1024
TAILLE_MAX_VIDEO_OCTETS = int(os.getenv("AYYOU_TAILLE_MAX_VIDEO_MO", "200")) * 1024 * 1024
DUREE_MAX_VIDEO_SECONDES = 300
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# --- Django REST Framework ----------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "applications.communs.erreurs.gestionnaire_exceptions",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("AYYOU_LIMITE_ANONYME", "100/minute"),
        "user": os.getenv("AYYOU_LIMITE_UTILISATEUR", "300/minute"),
        "connexion": "10/minute",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("AYYOU_DUREE_JETON_ACCES_MINUTES", "30"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("AYYOU_DUREE_JETON_RAFRAICHISSEMENT_JOURS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "API AYYOU",
    "DESCRIPTION": "Backend de la plateforme AYYOU : découverte culinaire, commande, paiement PayTech et livraison.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# --- CORS (Cross-Origin Resource Sharing) -------------------------------------
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "http://localhost:59942",
    "http://127.0.0.1:59942",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
] + [origine for origine in lire_liste("AYYOU_ORIGINES_FRONTEND", "https://ayyou.site,http://localhost:2401,http://127.0.0.1:2401") if origine]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",
    r"^http://127\.0\.0\.1:\d+$",
]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

# --- Paramètres métier AYYOU --------------------------------------------------
FRAIS_LIVRAISON_PAR_DEFAUT_FCFA = int(os.getenv("AYYOU_FRAIS_LIVRAISON_DEFAUT_FCFA", "1000"))
NOMBRE_MAX_ESSAIS_CODE_LIVRAISON = 5
URL_FRONTEND = os.getenv("AYYOU_URL_FRONTEND", "http://localhost:4200")
URL_PUBLIQUE_BACKEND = os.getenv("AYYOU_URL_PUBLIQUE_BACKEND", "http://localhost:8000")

# --- Envoi d'e-mails (SMTP réel avec variables d'environnement) ---------------
EMAIL_HOST_USER = (os.getenv("AYYOU_EMAIL_HOST_USER") or os.getenv("EMAIL_HOST_USER") or "").strip()
EMAIL_HOST_PASSWORD = (os.getenv("AYYOU_EMAIL_HOST_PASSWORD") or os.getenv("EMAIL_HOST_PASSWORD") or "").strip("\"' ")
EMAIL_HOST = os.getenv("AYYOU_EMAIL_HOST") or os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("AYYOU_EMAIL_PORT") or os.getenv("EMAIL_PORT", "465"))

# Configuration automatique TLS / SSL selon le port utilisé
if EMAIL_PORT == 465:
    EMAIL_USE_SSL = lire_booleen("AYYOU_EMAIL_USE_SSL", lire_booleen("EMAIL_USE_SSL", True))
    EMAIL_USE_TLS = lire_booleen("AYYOU_EMAIL_USE_TLS", lire_booleen("EMAIL_USE_TLS", False))
else:
    EMAIL_USE_TLS = lire_booleen("AYYOU_EMAIL_USE_TLS", lire_booleen("EMAIL_USE_TLS", True))
    EMAIL_USE_SSL = lire_booleen("AYYOU_EMAIL_USE_SSL", lire_booleen("EMAIL_USE_SSL", False))

EMAIL_TIMEOUT = int(os.getenv("AYYOU_EMAIL_TIMEOUT", os.getenv("EMAIL_TIMEOUT", "10")))

EMAIL_BACKEND = os.getenv(
    "AYYOU_EMAIL_BACKEND",
    os.getenv(
        "EMAIL_BACKEND",
        "django.core.mail.backends.smtp.EmailBackend"
        if EMAIL_HOST_USER
        else "django.core.mail.backends.console.EmailBackend",
    ),
)

_default_from_env = os.getenv("AYYOU_DEFAULT_FROM_EMAIL") or os.getenv("DEFAULT_FROM_EMAIL")
if _default_from_env:
    DEFAULT_FROM_EMAIL = _default_from_env
elif EMAIL_HOST_USER:
    DEFAULT_FROM_EMAIL = f"AYYOU <{EMAIL_HOST_USER}>"
else:
    DEFAULT_FROM_EMAIL = "AYYOU <contact@ayyou.site>"

SERVER_EMAIL = DEFAULT_FROM_EMAIL

# --- PayTech ------------------------------------------------------------------
PAYTECH_URL_BASE = os.getenv("PAYTECH_URL_BASE", "https://paytech.sn/api")
PAYTECH_CLE_API = os.getenv("PAYTECH_CLE_API", "")
PAYTECH_CLE_SECRETE = os.getenv("PAYTECH_CLE_SECRETE", "")
PAYTECH_ENVIRONNEMENT = os.getenv("PAYTECH_ENVIRONNEMENT", "test")  # "test" ou "prod"
PAYTECH_DELAI_ATTENTE_SECONDES = int(os.getenv("PAYTECH_DELAI_ATTENTE_SECONDES", "15"))

# --- Service IA (FastAPI) -----------------------------------------------------
SERVICE_IA_URL = os.getenv("AYYOU_SERVICE_IA_URL", "http://127.0.0.1:8001")
SERVICE_IA_CLE_INTERNE = os.getenv("AYYOU_SERVICE_IA_CLE_INTERNE", "cle-secrete-interne-ayyou-ia-2026")
SERVICE_IA_DELAI_ATTENTE_SECONDES = int(os.getenv("AYYOU_SERVICE_IA_DELAI_SECONDES", "8"))

# --- Journalisation (sans données personnelles ni secrets) --------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{asctime}] {levelname} {name} : {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "loggers": {
        "ayyou": {"handlers": ["console"], "level": os.getenv("AYYOU_NIVEAU_JOURNAL", "INFO")},
    },
}

# --- Durcissement production --------------------------------------------------
CSRF_TRUSTED_ORIGINS = [
    origine
    for origine in lire_liste(
        "AYYOU_CSRF_ORIGINES",
        "https://api.ayyou.site,https://ayyou.site,http://localhost:2401,http://127.0.0.1:2401,http://localhost:8888,http://127.0.0.1:8888",
    )
    if origine
]

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
