"""
Vues HTTP pour le domaine Commande.

Endpoints disponibles :
- POST /api/commandes/ : Créer une commande depuis le panier (Client)
- GET  /api/commandes/ : Historique des commandes du client connecté
- GET  /api/commandes/<id>/ : Détail et suivi d'une commande (Client)
- GET  /api/commandes/restaurant/ : Liste des commandes pour l'établissement (Gérant)
- POST /api/commandes/<id>/accepter/ : Accepter la commande (Gérant)
- POST /api/commandes/<id>/refuser/ : Refuser la commande avec motif (Gérant)
- POST /api/commandes/<id>/marquer-prete/ : Marquer prête pour coursier (Gérant)
- POST /api/commandes/<id>/valider-pin/ : Valider le code PIN de remise (Livreur)
- GET  /api/commandes/<id>/historique/ : Journal d'audit de la commande (Acteurs autorisés)
"""

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from applications.communs.erreurs import AccesRefuse
from applications.etablissements.services import obtenir_etablissement_du_gerant
from applications.utilisateurs.permissions import EstClient, EstGerantEtablissement, EstLivreur

from .models import Commande, HistoriqueStatutCommande, StatutCommande
from .serializers import (
    SerializerActionAcceptation,
    SerializerActionRefus,
    SerializerCommandeClient,
    SerializerCommandeRestaurant,
    SerializerCreationCommande,
    SerializerEstimationCommande,
    SerializerHistoriqueStatut,
    SerializerValidationPin,
)
from .services import (
    accepter_commande_par_restaurant,
    creer_commande_depuis_panier,
    estimer_montants_commande,
    marquer_commande_prete,
    refuser_commande_par_restaurant,
)


class VueCommandesClient(generics.ListCreateAPIView):
    """
    Espace Client :
    - GET  : Liste de ses commandes avec statut et articles.
    - POST : Valide le sous-panier d'un restaurant et génère une commande.
    """

    permission_classes = [EstClient]
    serializer_class = SerializerCommandeClient

    def get_queryset(self):
        return (
            Commande.objects.filter(client=self.request.user)
            .select_related("etablissement", "client")
            .prefetch_related("lignes", "livraison__livreur__utilisateur")
        )

    def create(self, request, *args, **kwargs):
        serializer = SerializerCreationCommande(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data

        commande = creer_commande_depuis_panier(
            client=request.user,
            etablissement_id=donnees["etablissement_id"],
            adresse_livraison=donnees["adresse_livraison"],
            latitude_livraison=donnees["latitude_livraison"],
            longitude_livraison=donnees["longitude_livraison"],
            telephone_contact=donnees["telephone_contact"],
            repere_livraison=donnees["repere_livraison"],
            instructions_livraison=donnees["instructions_livraison"],
            mode_paiement=donnees["mode_paiement"],
            source_video_id=donnees["source_video_id"],
            articles_payload=donnees.get("articles"),
        )

        reponse_serializer = SerializerCommandeClient(commande, context={"request": request})
        return Response(reponse_serializer.data, status=status.HTTP_201_CREATED)


class VueEstimationCommande(APIView):
    """
    POST /api/commandes/estimation/
    Renvoie sous-total, frais de livraison et total exacts pour la position choisie,
    AVANT de créer la commande. Le total affiché est celui qui sera payé.
    """

    permission_classes = [EstClient]

    def post(self, request):
        serializer = SerializerEstimationCommande(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data
        montants = estimer_montants_commande(
            etablissement_id=donnees["etablissement_id"],
            articles=donnees["articles"],
            latitude=donnees["latitude_livraison"],
            longitude=donnees["longitude_livraison"],
        )
        return Response(montants)


class VueDetailCommandeClient(generics.RetrieveAPIView):
    """Détail et suivi d'une commande par le client (par ID numérique ou référence)."""

    permission_classes = [EstClient]
    serializer_class = SerializerCommandeClient

    def get_queryset(self):
        return (
            Commande.objects.filter(client=self.request.user)
            .select_related("etablissement", "client")
            .prefetch_related("lignes", "livraison__livreur__utilisateur")
        )

    def get_object(self):
        pk_or_ref = str(self.kwargs.get("pk", "")).strip()
        queryset = self.get_queryset()
        if pk_or_ref.isdigit():
            obj = queryset.filter(pk=int(pk_or_ref)).first()
            if obj:
                return obj
        obj = queryset.filter(reference=pk_or_ref).first()
        if obj:
            return obj
        from rest_framework.exceptions import NotFound
        raise NotFound("Commande introuvable.")


class VueCommandesRestaurant(generics.ListAPIView):
    """
    Espace Gérant (Kanban cuisine) :
    Affiche toutes les commandes destinées à son établissement.
    """

    permission_classes = [EstGerantEtablissement]
    serializer_class = SerializerCommandeRestaurant
    pagination_class = None

    def get_queryset(self):
        etablissement = obtenir_etablissement_du_gerant(self.request.user)
        queryset = (
            Commande.objects.filter(etablissement=etablissement)
            .exclude(statut=StatutCommande.EN_ATTENTE_PAIEMENT)
            .select_related("client")
            .prefetch_related("lignes")
        )
        if statut := self.request.query_params.get("statut"):
            queryset = queryset.filter(statut=statut)
        return queryset


def get_commande_par_pk_ou_reference(pk_val) -> Commande:
    """Récupère une commande soit par son identifiant numérique, soit par sa référence ORD-XXXX."""
    from rest_framework.exceptions import NotFound
    pk_str = str(pk_val).strip()
    if pk_str.isdigit():
        cmd = Commande.objects.filter(pk=int(pk_str)).first()
        if cmd:
            return cmd
    cmd = Commande.objects.filter(reference=pk_str).first()
    if cmd:
        return cmd
    raise NotFound(f"Commande « {pk_val} » introuvable.")


class VueAccepterCommande(APIView):
    """Le gérant accepte la commande et définit le temps de préparation estimé."""

    permission_classes = [EstGerantEtablissement]

    def post(self, request, pk):
        commande = get_commande_par_pk_ou_reference(pk)
        serializer = SerializerActionAcceptation(data=request.data)
        serializer.is_valid(raise_exception=True)
        delai = serializer.validated_data.get("delai_minutes", 25)

        commande_maj = accepter_commande_par_restaurant(commande, request.user, delai_minutes=delai)
        return Response(SerializerCommandeRestaurant(commande_maj).data)


class VueRefuserCommande(APIView):
    """Le gérant refuse la commande avec un motif obligatoire."""

    permission_classes = [EstGerantEtablissement]

    def post(self, request, pk):
        commande = get_commande_par_pk_ou_reference(pk)
        serializer = SerializerActionRefus(data=request.data)
        serializer.is_valid(raise_exception=True)
        motif = serializer.validated_data["motif"]

        commande_maj = refuser_commande_par_restaurant(commande, request.user, motif=motif)
        return Response(SerializerCommandeRestaurant(commande_maj).data)


class VueMarquerPreteCommande(APIView):
    """Le gérant marque la commande comme prête pour la prise en charge coursier."""

    permission_classes = [EstGerantEtablissement]

    def post(self, request, pk):
        commande = get_commande_par_pk_ou_reference(pk)
        commande_maj = marquer_commande_prete(commande, request.user)
        return Response(SerializerCommandeRestaurant(commande_maj).data)


class VueValiderPinLivraison(APIView):
    """
    Clôture par PIN via l'identifiant de commande.
    Même règle que /api/livraisons/mission-en-cours/valider-pin/ : seul le livreur
    assigné à CETTE commande peut saisir le PIN, avec un nombre d'essais limité.
    """

    permission_classes = [EstLivreur]

    def post(self, request, pk):
        from applications.livraisons.services import obtenir_profil_livreur, valider_livraison_avec_pin

        commande = get_commande_par_pk_ou_reference(pk)
        serializer = SerializerValidationPin(data=request.data)
        serializer.is_valid(raise_exception=True)

        profil = obtenir_profil_livreur(request.user)
        livraison = getattr(commande, "livraison", None)
        if livraison is None or livraison.livreur_id != profil.id:
            raise AccesRefuse("Cette commande n'est pas assignée à votre compte livreur.")

        valider_livraison_avec_pin(profil, serializer.validated_data["code_pin"])
        return Response({
            "succes": True,
            "message": "Code PIN validé avec succès. Commande marquée comme livrée.",
            "statut": StatutCommande.LIVREE,
        })


class VueHistoriqueCommande(generics.ListAPIView):
    """Audit des transitions pour une commande donnée."""

    serializer_class = SerializerHistoriqueStatut

    def get_queryset(self):
        commande = get_object_or_404(Commande, pk=self.kwargs["pk"])
        user = self.request.user

        # Contrôle d'accès : le client de la commande, le gérant de l'établissement ou l'admin
        est_client_commande = user.id == commande.client_id
        est_gerant_commande = (
            user.role == "RESTAURANT"
            and hasattr(user, "etablissement")
            and user.etablissement.id == commande.etablissement_id
        )
        if not (user.is_superuser or est_client_commande or est_gerant_commande):
            raise AccesRefuse("Vous n'êtes pas autorisé à consulter l'historique de cette commande.")

        return HistoriqueStatutCommande.objects.filter(commande=commande)
