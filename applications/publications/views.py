"""
Vues HTTP pour le domaine Publications (Fil immersif d'accueil et Ayyou Studio).
"""

from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.etablissements.services import obtenir_etablissement_du_gerant
from applications.utilisateurs.permissions import EstGerantEtablissement

from .models import MentionJeaime, Publication
from .serializers import (
    SerializerCreationPublication,
    SerializerPublicationFil,
    SerializerStudioVideoItem,
)


class VueFilPublications(generics.ListAPIView):
    """Fil immersif de découverte culinaire (public ou connecté)."""

    permission_classes = [AllowAny]
    serializer_class = SerializerPublicationFil

    def get_queryset(self):
        qs = (
            Publication.objects.filter(est_publie=True, etablissement__statut_validation="ACTIF")
            .select_related("etablissement", "plat")
            .prefetch_related("mentions_jeaime")
        )
        etablissement_id = self.request.query_params.get("etablissement") or self.request.query_params.get("etablissement_id")
        if etablissement_id:
            qs = qs.filter(etablissement_id=etablissement_id)
        return qs


class VueDetailPublication(generics.RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = SerializerPublicationFil

    def get_queryset(self):
        return Publication.objects.filter(est_publie=True).select_related("etablissement", "plat")


class VueToggleLikePublication(APIView):
    """Aimer ou retirer son j'aime sur une vidéo ou photo culinaire."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        pub = get_object_or_404(Publication, pk=pk)
        mention, cree = MentionJeaime.objects.get_or_create(utilisateur=request.user, publication=pub)

        if not cree:
            mention.delete()
            aime = False
        else:
            aime = True

        total_likes = pub.mentions_jeaime.count()
        return Response(
            {
                "estAime": aime,
                "nombreJeaime": str(total_likes),
                "message": "Mention J'aime ajoutée." if aime else "Mention J'aime retirée.",
            }
        )


class VueIncrementerVue(APIView):
    """Enregistre une vue sur une publication (utilisé par le composant Reel)."""

    permission_classes = [AllowAny]

    def post(self, request, pk):
        Publication.objects.filter(pk=pk).update(nombre_vues=F("nombre_vues") + 1)
        return Response({"succes": True})


class VueIncrementerPartage(APIView):
    """Enregistre un partage d'une vidéo."""

    permission_classes = [AllowAny]

    def post(self, request, pk):
        Publication.objects.filter(pk=pk).update(nombre_partages=F("nombre_partages") + 1)
        return Response({"succes": True})


class VueStudioPublications(APIView):
    """
    Espace Ayyou Studio pour le Gérant Restaurant :
    - GET  : Liste de ses publications vidéo et photo
    - POST : Téléversement d'une nouvelle vidéo (max 300s) ou photo
    """

    permission_classes = [EstGerantEtablissement]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        etablissement = obtenir_etablissement_du_gerant(request.user)
        publications = Publication.objects.filter(etablissement=etablissement).prefetch_related("mentions_jeaime")
        return Response(SerializerStudioVideoItem(publications, many=True, context={"request": request}).data)

    def post(self, request):
        etablissement = obtenir_etablissement_du_gerant(request.user)
        serializer = SerializerCreationPublication(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        pub = serializer.save(etablissement=etablissement)
        return Response(
            SerializerStudioVideoItem(pub, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class VueSupprimerPublicationStudio(APIView):
    """Suppression d'une vidéo depuis son Ayyou Studio."""

    permission_classes = [EstGerantEtablissement]

    def delete(self, request, pk):
        etablissement = obtenir_etablissement_du_gerant(request.user)
        pub = get_object_or_404(Publication, pk=pk, etablissement=etablissement)
        pub.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
