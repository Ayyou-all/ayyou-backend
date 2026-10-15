"""
Vues HTTP des établissements.

| Méthode | URL                                      | Rôle            |
|---------|------------------------------------------|-----------------|
| GET     | /api/etablissements/                     | Public          |
| GET     | /api/etablissements/{id}/                | Public          |
| GET     | /api/etablissements/mon-etablissement/   | Restaurant      |
| PATCH   | /api/etablissements/mon-etablissement/   | Restaurant      |

Les plats d'un établissement : GET /api/plats/?etablissement={id} (application catalogue).
"""

from django.db.models import Count, Q
from rest_framework import generics
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny

from applications.utilisateurs.permissions import EstGerantEtablissement

from .serializers import SerializerEtablissementPublic, SerializerMonEtablissement
from .services import obtenir_etablissement_du_gerant, obtenir_etablissements_visibles


class VueListeEtablissements(generics.ListAPIView):
    """Liste publique. Filtres : ?recherche=, ?quartier=, ?ouverts=1"""

    serializer_class = SerializerEtablissementPublic
    permission_classes = [AllowAny]

    def get_queryset(self):
        parametres = self.request.query_params
        etablissements = obtenir_etablissements_visibles().annotate(nombre_abonnes=Count("abonnements"))
        if recherche := parametres.get("recherche"):
            etablissements = etablissements.filter(
                Q(nom__icontains=recherche) | Q(specialite__icontains=recherche) | Q(description__icontains=recherche)
            )
        if quartier := parametres.get("quartier"):
            etablissements = etablissements.filter(quartier_ville__icontains=quartier)
        if type_etablissement := parametres.get("type"):
            etablissements = etablissements.filter(type_etablissement=type_etablissement)
        if parametres.get("ouverts") == "1":
            etablissements = etablissements.filter(est_ouvert=True)
        return etablissements


class VueDetailEtablissement(generics.RetrieveAPIView):
    serializer_class = SerializerEtablissementPublic
    permission_classes = [AllowAny]

    def get_queryset(self):
        return obtenir_etablissements_visibles().annotate(nombre_abonnes=Count("abonnements"))


class VueMonEtablissement(generics.RetrieveUpdateAPIView):
    """Le gérant consulte et modifie SON établissement (jamais celui d'un autre)."""

    serializer_class = SerializerMonEtablissement
    permission_classes = [EstGerantEtablissement]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return obtenir_etablissement_du_gerant(self.request.user)
