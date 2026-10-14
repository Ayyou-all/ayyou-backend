"""
Vues HTTP pour la gestion des abonnements aux établissements AYYOU.
"""

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.etablissements.models import Etablissement

from .models import AbonnementEtablissement
from .serializers import SerializerAbonnement


class VueBasculerAbonnement(APIView):
    """
    Bascule l'abonnement d'un utilisateur à un établissement partenaire (restaurant).
    Ajoute l'abonnement s'il n'existe pas, ou le supprime s'il existe déjà.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, etablissement_id):
        etablissement = get_object_or_404(Etablissement, pk=etablissement_id)
        abonnement, cree = AbonnementEtablissement.objects.get_or_create(
            utilisateur=request.user,
            etablissement=etablissement,
        )

        if not cree:
            abonnement.delete()
            est_abonne = False
        else:
            est_abonne = True

        total_abonnes = etablissement.abonnements.count()

        return Response(
            {
                "estAbonne": est_abonne,
                "nombreAbonnes": total_abonnes,
                "message": (
                    f"Vous êtes maintenant abonné à {etablissement.nom}."
                    if est_abonne
                    else f"Vous n'êtes plus abonné à {etablissement.nom}."
                ),
            },
            status=status.HTTP_200_OK,
        )


class VueMesAbonnements(generics.ListAPIView):
    """
    Liste des établissements suivis par l'utilisateur connecté.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SerializerAbonnement

    def get_queryset(self):
        return (
            AbonnementEtablissement.objects.filter(utilisateur=self.request.user)
            .select_related("etablissement")
        )
