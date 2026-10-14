"""
Vues du catalogue.

| Méthode            | URL                                         | Accès              |
|--------------------|---------------------------------------------|--------------------|
| GET                | /api/categories/                            | Public             |
| GET                | /api/plats/?etablissement=&categorie=&recherche=&prix_max=&disponibles=1 | Public |
| GET                | /api/plats/{id}/                            | Public             |
| GET/POST           | /api/catalogue/mes-plats/                   | Restaurant         |
| GET/PATCH/DELETE   | /api/catalogue/mes-plats/{id}/              | Restaurant (propriétaire) |
| PATCH              | /api/catalogue/mes-plats/{id}/disponibilite/| Restaurant (propriétaire) |
"""

from rest_framework import generics, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from applications.etablissements.services import obtenir_etablissement_du_gerant
from applications.utilisateurs.permissions import EstGerantEtablissement

from .models import CategoriePlat, Plat
from .serializers import SerializerCategoriePlat, SerializerDisponibilite, SerializerGestionPlat, SerializerPlat
from .services import annoter_nombre_commandes, filtrer_plats, obtenir_plats_visibles


class VueListeCategories(generics.ListAPIView):
    queryset = CategoriePlat.objects.all()
    serializer_class = SerializerCategoriePlat
    permission_classes = [AllowAny]
    pagination_class = None


class VueListePlats(generics.ListAPIView):
    serializer_class = SerializerPlat
    permission_classes = [AllowAny]

    def get_queryset(self):
        plats = filtrer_plats(obtenir_plats_visibles(), self.request.query_params)
        return annoter_nombre_commandes(plats)


class VueDetailPlat(generics.RetrieveAPIView):
    serializer_class = SerializerPlat
    permission_classes = [AllowAny]

    def get_queryset(self):
        return annoter_nombre_commandes(obtenir_plats_visibles())


class EnsembleVuesMesPlats(viewsets.ModelViewSet):
    """
    Gestion du menu par le gérant. Le queryset est filtré sur SON établissement :
    un restaurant ne peut ni voir ni modifier le plat d'un autre (réponse 404).
    """

    serializer_class = SerializerGestionPlat
    permission_classes = [EstGerantEtablissement]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        etablissement = obtenir_etablissement_du_gerant(self.request.user)
        return Plat.objects.filter(etablissement=etablissement, est_archive=False).select_related("categorie")

    def perform_create(self, serializer):
        serializer.save(etablissement=obtenir_etablissement_du_gerant(self.request.user))

    def perform_destroy(self, plat):
        # Archivage plutôt que suppression : les commandes passées gardent leur référence.
        plat.est_archive = True
        plat.est_disponible = False
        plat.save(update_fields=["est_archive", "est_disponible", "date_modification"])

    @action(detail=True, methods=["patch"], url_path="disponibilite")
    def changer_disponibilite(self, request, pk=None):
        plat = self.get_object()
        serializer = SerializerDisponibilite(data=request.data)
        serializer.is_valid(raise_exception=True)
        plat.est_disponible = serializer.validated_data["est_disponible"]
        plat.save(update_fields=["est_disponible", "date_modification"])
        return Response(SerializerGestionPlat(plat, context={"request": request}).data)
