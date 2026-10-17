"""
Contrôle des fichiers téléversés et distribution des médias publics.

Pourquoi ?
- Un fichier envoyé par un utilisateur ne doit jamais pouvoir être un .html ou un .svg
  servi depuis notre domaine (risque de script malveillant).
- Les pièces justificatives (CNI, permis, RCCM...) sont privées : elles ne passent
  jamais par l'URL publique /medias/, seulement par une API protégée.
"""

import mimetypes
import os
import posixpath

from django.conf import settings
from django.http import Http404
from django.views.static import serve
from rest_framework import serializers

EXTENSIONS_IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSIONS_DOCUMENTS = {".pdf", ".jpg", ".jpeg", ".png"}
EXTENSIONS_VIDEOS = {".mp4", ".mov", ".webm", ".m4v"}
TAILLE_MAX_DOCUMENT_OCTETS = 10 * 1024 * 1024
# Types distribués publiquement par /medias/ (les .gif déjà présents restent lisibles).
EXTENSIONS_SERVIES = EXTENSIONS_IMAGES | {".gif"} | EXTENSIONS_VIDEOS

# Dossier (dans MEDIA_ROOT) des pièces justificatives : jamais servi publiquement.
DOSSIER_DOCUMENTS_PRIVES = "documents_partenaires/"


def _extension(fichier) -> str:
    return os.path.splitext(fichier.name or "")[1].lower()


def _verifier_image_lisible(fichier) -> None:
    """Ouvre réellement le fichier avec Pillow : un faux .jpg est refusé."""
    from PIL import Image

    try:
        image = Image.open(fichier)
        image.verify()
    except Exception:
        raise serializers.ValidationError("Le fichier n'est pas une image valide.")
    finally:
        fichier.seek(0)


def valider_image(fichier):
    """Validateur DRF pour une photo (profil, logo, couverture, plat)."""
    if not fichier:
        return fichier
    if _extension(fichier) not in EXTENSIONS_IMAGES:
        raise serializers.ValidationError("Formats d'image acceptés : JPG, JPEG, PNG, WEBP.")
    if fichier.size > settings.TAILLE_MAX_PHOTO_OCTETS:
        raise serializers.ValidationError("L'image dépasse la taille maximale autorisée.")
    _verifier_image_lisible(fichier)
    return fichier


def valider_document(fichier):
    """Validateur DRF pour une pièce justificative (PDF ou photo du document)."""
    if not fichier:
        return fichier
    extension = _extension(fichier)
    if extension not in EXTENSIONS_DOCUMENTS:
        raise serializers.ValidationError("Formats de document acceptés : PDF, JPG, JPEG, PNG.")
    if fichier.size > TAILLE_MAX_DOCUMENT_OCTETS:
        raise serializers.ValidationError("Le document ne doit pas dépasser 10 Mo.")
    if extension == ".pdf":
        debut = fichier.read(5)
        fichier.seek(0)
        if debut != b"%PDF-":
            raise serializers.ValidationError("Le fichier n'est pas un PDF valide.")
    else:
        _verifier_image_lisible(fichier)
    return fichier


def servir_media_public(request, path):
    """
    Remplace django.views.static.serve pour /medias/.
    Refuse les documents privés et tout type de fichier qui n'est pas une image ou une vidéo.
    """
    # normpath résout les « ../ » AVANT le contrôle, sinon « x/../documents_partenaires/... » passerait.
    chemin = posixpath.normpath(path).lstrip("/")
    if chemin.startswith(DOSSIER_DOCUMENTS_PRIVES):
        raise Http404("Document privé.")
    extension = os.path.splitext(chemin)[1].lower()
    if extension not in EXTENSIONS_SERVIES:
        raise Http404("Type de fichier non distribué.")
    if extension in EXTENSIONS_VIDEOS and request.headers.get("Range"):
        return servir_morceau_video(request, chemin)
    return serve(request, chemin, document_root=settings.MEDIA_ROOT)


TAILLE_MAX_MORCEAU = 2 * 1024 * 1024  # 2 Mo par réponse : adapté aux connexions mobiles


def servir_morceau_video(request, chemin):
    """
    Répond à une demande partielle « Range: bytes=debut-fin » (code 206).
    Safari sur iPhone refuse de lire une vidéo sans cela, et c'est ce qui permet
    d'avancer dans la vidéo sans tout télécharger.
    """
    from django.http import HttpResponse

    chemin_complet = os.path.join(settings.MEDIA_ROOT, chemin)
    if not os.path.isfile(chemin_complet):
        raise Http404("Fichier introuvable.")
    taille = os.path.getsize(chemin_complet)

    plage = request.headers["Range"].replace("bytes=", "").split(",")[0].strip()
    debut_texte, _, fin_texte = plage.partition("-")
    if debut_texte.isdigit():
        debut = int(debut_texte)
        fin = int(fin_texte) if fin_texte.isdigit() else taille - 1
    elif fin_texte.isdigit():  # « bytes=-500 » : les 500 derniers octets
        debut, fin = max(0, taille - int(fin_texte)), taille - 1
    else:
        return serve(request, chemin, document_root=settings.MEDIA_ROOT)
    fin = min(fin, taille - 1, debut + TAILLE_MAX_MORCEAU - 1)
    if debut >= taille or debut > fin:
        reponse = HttpResponse(status=416)
        reponse["Content-Range"] = f"bytes */{taille}"
        return reponse

    with open(chemin_complet, "rb") as fichier:
        fichier.seek(debut)
        morceau = fichier.read(fin - debut + 1)
    type_fichier = mimetypes.guess_type(chemin_complet)[0] or "application/octet-stream"
    reponse = HttpResponse(morceau, status=206, content_type=type_fichier)
    reponse["Content-Range"] = f"bytes {debut}-{fin}/{taille}"
    reponse["Accept-Ranges"] = "bytes"
    reponse["Content-Length"] = str(len(morceau))
    return reponse
