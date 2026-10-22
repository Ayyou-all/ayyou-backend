"""
Vues HTTP pour les fonctionnalités d'Intelligence Artificielle AYYOU.
"""

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.utilisateurs.permissions import AbonnementValide, EstGerantEtablissement

from .serializers import SerializerRequeteChatbot, SerializerRequeteRechercheVocale, SerializerRequeteRecommandations
from .services import (
    analyser_recherche_vocale,
    generer_rapport_hebdo_etablissement,
    obtenir_previsions_etablissement,
    recommander_plats_pour_client,
    repondre_au_message_chatbot,
    transcrire_fichier_audio,
)


class VueRecommandationsIA(APIView):
    """
    Suggestions culinaires déterministes et intelligentes pour le client.
    Accessible en public ou connecté (personnalisation renforcée si connecté).
    """

    permission_classes = [AllowAny]

    def get(self, request):
        budget = request.query_params.get("budget_max_fcfa")
        budget_int = int(budget) if budget and budget.isdigit() else None
        limite = request.query_params.get("limite", 10)
        limite_int = int(limite) if str(limite).isdigit() else 10

        resultats = recommander_plats_pour_client(
            utilisateur=request.user,
            budget_max=budget_int,
            limite=limite_int,
            request=request,
        )
        return Response(resultats)

    def post(self, request):
        serializer = SerializerRequeteRecommandations(data=request.data)
        serializer.is_valid(raise_exception=True)

        budget = serializer.validated_data.get("budget_max_fcfa")
        limite = serializer.validated_data.get("limite", 10)

        resultats = recommander_plats_pour_client(
            utilisateur=request.user,
            budget_max=budget,
            limite=limite,
            request=request,
        )
        return Response(resultats)


class VueChatbotCulinaire(APIView):
    """
    Chatbot culinaire interactif sous contrainte budgétaire.
    Analyse le message, comprend le budget et renvoie des cartes de plats réels cliquables.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SerializerRequeteChatbot(data=request.data)
        serializer.is_valid(raise_exception=True)

        message = serializer.validated_data["message"]
        budget = serializer.validated_data.get("budget_fcfa")
        quartier = serializer.validated_data.get("quartier")
        historique = serializer.validated_data.get("historique", [])

        reponse = repondre_au_message_chatbot(
            message_texte=message,
            budget_fcfa=budget,
            quartier=quartier,
            historique=historique,
            request=request,
        )
        return Response(reponse)


class VueRechercheVocale(APIView):
    """Recherche vocale : phrase dictée par le client -> filtres appliqués au catalogue."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SerializerRequeteRechercheVocale(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(analyser_recherche_vocale(serializer.validated_data["texte"]))


class VuePrevisionsRestaurant(APIView):
    """
    Prévisions d'affluence par heure et coups de feu en cuisine pour le restaurant du gérant.
    """

    permission_classes = [EstGerantEtablissement, AbonnementValide]

    def get(self, request):
        previsions = obtenir_previsions_etablissement(request.user)
        return Response(previsions)


class VueRapportHebdomadaireRestaurant(APIView):
    """
    Rapport managérial hebdomadaire pour le restaurant du gérant.
    """

    permission_classes = [EstGerantEtablissement, AbonnementValide]

    def get(self, request):
        rapport = generer_rapport_hebdo_etablissement(request.user)
        return Response(rapport)


class VueTranscriptionAudio(APIView):
    """
    Transcription vocale Speech-to-Text avec Whisper.
    Reçoit un fichier audio (WebM, WAV, etc.) et retourne le texte transcrit.
    """

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        fichier = request.FILES.get("fichier") or request.FILES.get("audio")
        if not fichier:
            audio_b64 = request.data.get("audio_base64")
            if audio_b64:
                import base64
                donnees = base64.b64decode(audio_b64)
                res = transcrire_fichier_audio(donnees, nom_fichier="audio.webm")
                return Response(res)
            return Response(
                {"succes": False, "message": "Aucun fichier audio fourni."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        octets = fichier.read()
        res = transcrire_fichier_audio(octets, nom_fichier=fichier.name)
        return Response(res)

