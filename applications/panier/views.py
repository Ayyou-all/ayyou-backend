"""
Vues du panier (rôle Client uniquement).

| Méthode | URL                              | Description                         |
|---------|----------------------------------|-------------------------------------|
| GET     | /api/panier/                     | Panier groupé par établissement     |
| DELETE  | /api/panier/                     | Vider le panier                     |
| POST    | /api/panier/lignes/              | Ajouter un plat                     |
| PATCH   | /api/panier/lignes/{id}/         | Modifier quantité / instructions    |
| DELETE  | /api/panier/lignes/{id}/         | Retirer une ligne                   |

Exemple : POST /api/panier/lignes/ {"plat_id": 12, "quantite": 2}
-> 201 (panier complet recalculé) | 400 {"code": "plat_indisponible", ...}
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.utilisateurs.permissions import EstClient

from .models import LignePanier
from .serializers import SerializerAjoutPanier, SerializerModificationLignePanier, serialiser_panier_groupe
from .services import ajouter_au_panier, calculer_panier_groupe, vider_panier


def _reponse_panier(requete, statut_http=status.HTTP_200_OK):
    return Response(serialiser_panier_groupe(calculer_panier_groupe(requete.user), requete), status=statut_http)


class VuePanier(APIView):
    permission_classes = [EstClient]

    def get(self, request):
        return _reponse_panier(request)

    def delete(self, request):
        # ?etablissement=<id> vide seulement le panier de ce restaurant
        etablissement_id = request.query_params.get("etablissement")
        vider_panier(request.user, etablissement_id=int(etablissement_id) if str(etablissement_id).isdigit() else None)
        return _reponse_panier(request)


class VueLignesPanier(APIView):
    permission_classes = [EstClient]

    def post(self, request):
        serializer = SerializerAjoutPanier(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data
        ajouter_au_panier(request.user, donnees["plat_id"], donnees["quantite"], donnees["instructions_speciales"])
        return _reponse_panier(request, status.HTTP_201_CREATED)


class VueLignePanier(APIView):
    permission_classes = [EstClient]

    def _obtenir_ligne(self, request, pk):
        # Filtre sur le client : impossible de modifier la ligne d'un autre client (404).
        return get_object_or_404(LignePanier, pk=pk, client=request.user)

    def patch(self, request, pk):
        serializer = SerializerModificationLignePanier(self._obtenir_ligne(request, pk), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return _reponse_panier(request)

    def delete(self, request, pk):
        self._obtenir_ligne(request, pk).delete()
        return _reponse_panier(request)
