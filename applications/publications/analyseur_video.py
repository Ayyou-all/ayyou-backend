"""
Module d'inspection et d'analyse des métadonnées vidéo pour AYYOU.

Vérifie :
1. La structure du conteneur vidéo (MP4 / QuickTime / WebM)
2. La durée réelle en secondes extraite de l'en-tête (atome mvhd)
3. La limite stricte de 300 secondes (5 minutes maximum) conformément aux règles AYYOU.
"""

import struct
from django.conf import settings

from applications.communs.erreurs import ErreurMetier


def extraire_duree_mp4_secondes(fichier_video) -> float | None:
    """
    Lit l'en-tête MP4/MOV de manière sécurisée en pur Python sans dépendre d'un binaire externe.
    Parcourt les boîtes (atoms) jusqu'à trouver 'moov' puis 'mvhd' (Movie Header Box).
    """
    position_initiale = fichier_video.tell() if hasattr(fichier_video, "tell") else 0
    try:
        if hasattr(fichier_video, "seek"):
            fichier_video.seek(0)

        # Taille maximale analysée dans l'en-tête (10 Mo suffisent largement)
        tampon = fichier_video.read(10 * 1024 * 1024)
        taille_totale = len(tampon)
        offset = 0

        while offset + 8 <= taille_totale:
            taille_boite, type_boite = struct.unpack(">I4s", tampon[offset : offset + 8])
            type_str = type_boite.decode("latin1", errors="ignore")

            if taille_boite == 1:
                # Large box 64-bit
                if offset + 16 > taille_totale:
                    break
                taille_boite = struct.unpack(">Q", tampon[offset + 8 : offset + 16])[0]
                entete_taille = 16
            else:
                entete_taille = 8

            if taille_boite < entete_taille:
                break

            if type_str == "moov":
                # Entrer dans la boîte 'moov' pour chercher 'mvhd'
                offset_moov = offset + entete_taille
                fin_moov = min(offset + taille_boite, taille_totale)

                while offset_moov + 8 <= fin_moov:
                    t_mvhd, typ_mvhd = struct.unpack(">I4s", tampon[offset_moov : offset_moov + 8])
                    if typ_mvhd.decode("latin1", errors="ignore") == "mvhd":
                        # Lecture de la boîte mvhd :
                        # version (1 octet), flags (3 octets)
                        version = tampon[offset_moov + 8]
                        if version == 1:
                            # 64-bit creation, modification, 32-bit timescale, 64-bit duration
                            donnees = tampon[offset_moov + 12 : offset_moov + 40]
                            timescale, duree = struct.unpack(">IQ", donnees[16:28])
                        else:
                            # 32-bit creation, modification, 32-bit timescale, 32-bit duration
                            donnees = tampon[offset_moov + 12 : offset_moov + 28]
                            timescale, duree = struct.unpack(">II", donnees[8:16])

                        if timescale > 0:
                            return duree / float(timescale)
                        break

                    if t_mvhd <= 0:
                        break
                    offset_moov += t_mvhd

                break

            offset += taille_boite

    except Exception:
        # En cas de format complexe ou partiel, on ne bloque pas si non décodable
        return None
    finally:
        if hasattr(fichier_video, "seek"):
            fichier_video.seek(position_initiale)

    return None


def valider_fichier_video(fichier_video) -> float | None:
    """
    Vérifie la conformité d'un fichier vidéo :
    - Taille maximale (settings.TAILLE_MAX_VIDEO_OCTETS)
    - Durée maximale de 300 secondes (5 minutes)
    """
    taille_max = getattr(settings, "TAILLE_MAX_VIDEO_OCTETS", 200 * 1024 * 1024)
    if fichier_video.size > taille_max:
        mo_max = taille_max // (1024 * 1024)
        raise ErreurMetier(
            f"La vidéo dépasse la taille maximale autorisée de {mo_max} Mo.",
            code="taille_video_depassee",
        )

    nom_fichier = getattr(fichier_video, "name", "").lower()
    extensions_valides = (".mp4", ".mov", ".webm", ".m4v")
    if not any(nom_fichier.endswith(ext) for ext in extensions_valides):
        raise ErreurMetier(
            "Format vidéo non pris en charge. Formats acceptés : MP4, MOV, WebM.",
            code="format_video_invalide",
        )

    duree_secondes = extraire_duree_mp4_secondes(fichier_video)
    duree_max = getattr(settings, "DUREE_MAX_VIDEO_SECONDES", 300)

    if duree_secondes is not None:
        if duree_secondes > duree_max:
            duree_arrondie = int(duree_secondes)
            raise ErreurMetier(
                f"La durée de la vidéo ({duree_arrondie}s) dépasse la limite autorisée de 5 minutes (300 secondes).",
                code="duree_video_trop_longue",
                details={"duree_secondes": duree_secondes, "duree_max_secondes": duree_max},
            )

    return duree_secondes
