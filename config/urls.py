"""
Configuration des URLs principales du backend AYYOU.

Toutes les APIs REST sont préfixées par `/api/`.
Documentation interactive OpenAPI / Swagger disponible sur `/api/docs/`.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.views.static import serve
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def vue_sante(_requete):
    """Point de contrôle de santé pour Docker et le reverse proxy."""
    return JsonResponse({"statut": "operationnel", "service": "ayyou-backend"})


urlpatterns = [
    # Route de santé pour Docker
    path("sante/", vue_sante, name="sante"),
    path("api/sante/", vue_sante, name="api-sante"),
    # Administration native Django
    path("admin/", admin.site.urls),
    # Documentation OpenAPI / Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # Applications métier AYYOU
    path("api/authentification/", include("applications.authentification.urls")),
    path("api/utilisateurs/", include("applications.utilisateurs.urls")),
    path("api/etablissements/", include("applications.etablissements.urls")),
    path("api/", include("applications.catalogue.urls")),
    path("api/panier/", include("applications.panier.urls")),
    path("api/commandes/", include("applications.commandes.urls")),
    path("api/paiements/", include("applications.paiements.urls")),
    path("api/livraisons/", include("applications.livraisons.urls")),
    path("api/publications/", include("applications.publications.urls")),
    path("api/abonnements/", include("applications.abonnements.urls")),
    path("api/notifications/", include("applications.notifications.urls")),
    path("api/administration/", include("applications.administration.urls")),
    path("api/ia/", include("applications.intelligence.urls")),
    # Distribution des fichiers médias téléversés (photos de plats, logos, bannières)
    re_path(r"^medias/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
