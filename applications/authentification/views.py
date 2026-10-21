"""
Vues d'authentification.

| Méthode | URL                                   | Accès        |
|---------|---------------------------------------|--------------|
| POST    | /api/authentification/inscription/    | Public       |
| POST    | /api/authentification/connexion/      | Public       |
| POST    | /api/authentification/rafraichir/     | Public (jeton de rafraîchissement) |
| POST    | /api/authentification/deconnexion/    | Connecté     |
| POST    | /api/authentification/mot-de-passe-oublie/        | Public |
| POST    | /api/authentification/reinitialiser-mot-de-passe/ | Public |

Exemple — connexion :
    POST {"identifiant": "fatou.diop@ayyou.sn", "mot_de_passe": "MotDePasse!2026"}
    200  {"jeton_acces": "...", "jeton_rafraichissement": "...", "utilisateur": {...}}
    400  {"code": "identifiants_invalides", "message": "Identifiant ou mot de passe incorrect."}
"""

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from applications.communs.erreurs import ErreurMetier
from applications.utilisateurs.serializers import SerializerUtilisateur

from .serializers import (
    SerializerConnexion,
    SerializerDemandeCode,
    SerializerInscription,
    SerializerRafraichissement,
    SerializerReinitialisationMotDePasse,
    SerializerVerificationCode,
)
from .services import (
    authentifier,
    creer_compte,
    demander_reinitialisation_mot_de_passe,
    generer_et_envoyer_code_verification,
    generer_jetons,
    reinitialiser_mot_de_passe,
    verifier_code_email,
)


def _reponse_session(utilisateur, requete, statut_http=status.HTTP_200_OK):
    corps = {**generer_jetons(utilisateur), "utilisateur": SerializerUtilisateur(utilisateur, context={"request": requete}).data}
    return Response(corps, status=statut_http)


from rest_framework.parsers import FormParser, JSONParser, MultiPartParser


class VueInscription(APIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "connexion"

    def post(self, request):
        serializer = SerializerInscription(data=request.data)
        serializer.is_valid(raise_exception=True)
        utilisateur = creer_compte(serializer.validated_data)
        return _reponse_session(utilisateur, request, status.HTTP_201_CREATED)


class VueConnexion(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "connexion"  # limite les tentatives de devinette de mot de passe

    def post(self, request):
        serializer = SerializerConnexion(data=request.data)
        serializer.is_valid(raise_exception=True)
        utilisateur = authentifier(serializer.validated_data["identifiant"], serializer.validated_data["mot_de_passe"])
        return _reponse_session(utilisateur, request)


class VueRafraichissement(APIView):
    """Échange un jeton de rafraîchissement contre une nouvelle paire (rotation + liste noire)."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SerializerRafraichissement(data=request.data)
        serializer.is_valid(raise_exception=True)
        # On réutilise le serializer officiel de SimpleJWT (contrat externe : clé "refresh").
        serializer_officiel = TokenRefreshSerializer(data={"refresh": serializer.validated_data["jeton_rafraichissement"]})
        try:
            serializer_officiel.is_valid(raise_exception=True)
        except (TokenError, InvalidToken, ValidationError):
            raise ErreurMetier("Session expirée, veuillez vous reconnecter.", code="jeton_invalide")
        jetons = serializer_officiel.validated_data
        return Response({"jeton_acces": jetons["access"], "jeton_rafraichissement": jetons.get("refresh")})


class VueDeconnexion(APIView):
    """Invalide le jeton de rafraîchissement (le jeton d'accès expire de lui-même)."""

    def post(self, request):
        serializer = SerializerRafraichissement(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["jeton_rafraichissement"]).blacklist()
        except TokenError:
            pass  # déjà invalide : la déconnexion est quand même considérée réussie
        return Response({"message": "Déconnexion réussie."})


class VueEnvoyerCodeVerification(APIView):
    """Envoie un code de vérification à 6 chiffres par e-mail via SMTP."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "connexion"

    def post(self, request):
        serializer = SerializerDemandeCode(data=request.data)
        serializer.is_valid(raise_exception=True)
        resultat = generer_et_envoyer_code_verification(serializer.validated_data["courriel"])
        return Response(resultat, status=status.HTTP_200_OK)


class VueVerifierCodeVerification(APIView):
    """Valide le code de vérification saisi avant l'inscription."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "connexion"

    def post(self, request):
        serializer = SerializerVerificationCode(data=request.data)
        serializer.is_valid(raise_exception=True)
        verifier_code_email(serializer.validated_data["courriel"], serializer.validated_data["code"])
        return Response({"succes": True, "valide": True, "message": "Code de vérification validé avec succès."})


class VueMotDePasseOublie(APIView):
    """Envoie un code de réinitialisation par e-mail (réponse identique que le compte existe ou non)."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "connexion"

    def post(self, request):
        serializer = SerializerDemandeCode(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(demander_reinitialisation_mot_de_passe(serializer.validated_data["courriel"]))


class VueReinitialiserMotDePasse(APIView):
    """Vérifie le code reçu par e-mail et enregistre le nouveau mot de passe."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "connexion"

    def post(self, request):
        serializer = SerializerReinitialisationMotDePasse(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data
        reinitialiser_mot_de_passe(donnees["courriel"], donnees["code"], donnees["nouveau_mot_de_passe"])
        return Response({"succes": True, "message": "Mot de passe modifié. Vous pouvez maintenant vous connecter."})
