"""
Configuration des URLs principales du backend AYYOU.

Toutes les APIs REST sont préfixées par `/api/`.
Documentation interactive OpenAPI / Swagger disponible sur `/api/docs/`.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
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
]

# En développement : distribution des fichiers médias téléversés
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
