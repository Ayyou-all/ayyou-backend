"""
Vues du profil utilisateur.

| Méthode   | URL                                  | Accès                        |
|-----------|--------------------------------------|------------------------------|
| GET/PATCH | /api/utilisateurs/moi/               | Connecté                     |
| GET/POST  | /api/utilisateurs/moi/documents/     | Restaurant, Livreur         |
| GET       | /api/utilisateurs/documents/{id}/fichier/ | Propriétaire ou Admin  |
"""

from django.http import FileResponse, Http404
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import DocumentJustificatif, Role
from .permissions import EstPartenaire
from .serializers import (
    SerializerChangementMotDePasse,
    SerializerDocumentJustificatif,
    SerializerModificationProfil,
    SerializerUtilisateur,
)


class VueMonProfil(generics.RetrieveUpdateAPIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        return SerializerModificationProfil if self.request.method == "PATCH" else SerializerUtilisateur

    def update(self, request, *args, **kwargs):
        serializer = SerializerModificationProfil(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(SerializerUtilisateur(request.user, context={"request": request}).data)


class VueMesDocuments(generics.ListCreateAPIView):
    """Le partenaire téléverse ses pièces légales ; seul l'admin change leur statut."""

    serializer_class = SerializerDocumentJustificatif
    permission_classes = [EstPartenaire]
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = None

    def get_queryset(self):
        return DocumentJustificatif.objects.filter(proprietaire=self.request.user)

    def perform_create(self, serializer):
        serializer.save(proprietaire=self.request.user)


class VueChangerMotDePasse(generics.GenericAPIView):
    """Permet à un utilisateur connecté de modifier son mot de passe de façon sécurisée."""

    parser_classes = [JSONParser, FormParser]

    def post(self, request, *args, **kwargs):
        serializer = SerializerChangementMotDePasse(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["nouveau_mot_de_passe"])
        request.user.save(update_fields=["password"])

        return Response({"message": "Votre mot de passe a été modifié avec succès."})



class VueFichierDocument(APIView):
    """
    Télécharge une pièce justificative.
    Seuls le propriétaire du document et un administrateur y ont accès ;
    pour tout autre compte, on répond 404 (on ne révèle pas que le document existe).
    """

    def get(self, request, pk):
        document = DocumentJustificatif.objects.filter(pk=pk).first()
        est_admin = request.user.role == Role.ADMINISTRATEUR or request.user.is_superuser
        if document is None or not (est_admin or document.proprietaire_id == request.user.id):
            raise Http404("Document introuvable.")
        if not document.fichier:
            raise Http404("Fichier absent.")
        return FileResponse(document.fichier.open("rb"), as_attachment=False, filename=document.fichier.name.split("/")[-1])
