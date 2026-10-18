"""
Vues HTTP pour le domaine Publications (Fil immersif d'accueil et Ayyou Studio).
"""

from django.db.models import F
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.etablissements.models import filtre_abonnement_valide
from applications.etablissements.services import obtenir_etablissement_du_gerant
from applications.utilisateurs.permissions import AbonnementValide, EstGerantEtablissement

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
            Publication.objects.filter(filtre_abonnement_valide("etablissement__"), est_publie=True, etablissement__statut_validation="ACTIF")
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
                "nombreJeaime": total_likes,
                "message": "Mention J'aime ajoutée." if aime else "Mention J'aime retirée.",
            }
        )


def identifiant_spectateur(request) -> str:
    """Utilisateur connecté, sinon adresse IP : sert à ne compter qu'une fois la même personne."""
    if request.user.is_authenticated:
        return f"u{request.user.pk}"
    return f"ip{request.META.get('REMOTE_ADDR', '')}"


def compter_une_fois(request, publication_id: int, action: str, duree_secondes: int) -> bool:
    """Vrai si cette personne n'a pas déjà fait cette action sur cette publication récemment."""
    cle = f"ayyou:{action}:{publication_id}:{identifiant_spectateur(request)}"
    return cache.add(cle, True, timeout=duree_secondes)


class VueIncrementerVue(APIView):
    """
    POST /api/publications/<id>/vue/
    Enregistre une vue (une seule par personne et par publication toutes les 6 heures)
    et renvoie le compteur réel enregistré en base.
    """

    permission_classes = [AllowAny]

    def post(self, request, pk):
        publication = get_object_or_404(Publication, pk=pk, est_publie=True)
        comptee = compter_une_fois(request, pk, "vue", 6 * 3600)
        if comptee:
            Publication.objects.filter(pk=pk).update(nombre_vues=F("nombre_vues") + 1)
            publication.refresh_from_db(fields=["nombre_vues"])
        return Response({"comptee": comptee, "nombreVues": publication.nombre_vues})


class VueIncrementerPartage(APIView):
    """POST /api/publications/<id>/partage/ : un partage par personne et par publication et par heure."""

    permission_classes = [AllowAny]

    def post(self, request, pk):
        publication = get_object_or_404(Publication, pk=pk, est_publie=True)
        comptee = compter_une_fois(request, pk, "partage", 3600)
        if comptee:
            Publication.objects.filter(pk=pk).update(nombre_partages=F("nombre_partages") + 1)
            publication.refresh_from_db(fields=["nombre_partages"])
        return Response({"comptee": comptee, "nombrePartages": publication.nombre_partages})


class VueStudioPublications(APIView):
    """
    Espace Ayyou Studio pour le Gérant Restaurant :
    - GET  : Liste de ses publications vidéo et photo
    - POST : Téléversement d'une nouvelle vidéo (max 300s) ou photo
    """

    permission_classes = [EstGerantEtablissement, AbonnementValide]
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

    permission_classes = [EstGerantEtablissement, AbonnementValide]

    def delete(self, request, pk):
        etablissement = obtenir_etablissement_du_gerant(request.user)
        pub = get_object_or_404(Publication, pk=pk, etablissement=etablissement)
        pub.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
