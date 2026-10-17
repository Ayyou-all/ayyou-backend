"""
Tests automatisés pour le domaine Publications et Reels culinaires AYYOU.

Scénarios validés :
1. Règle absolue des 300 secondes : rejet d'une vidéo de plus de 5 minutes.
2. Acceptation d'une vidéo conforme (<= 300s) et extraction de sa durée.
3. Affichage du fil d'accueil (uniquement les restaurants actifs, format adapté au frontend).
4. Bascule (toggle) de mention J'aime avec unicité par utilisateur.
5. Gestion Studio par le gérant (téléversement, association plat, suppression protégée).
"""

from unittest.mock import patch
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from applications.catalogue.models import CategoriePlat, Plat
from applications.communs.choix import StatutValidationPartenaire
from applications.communs.erreurs import ErreurMetier
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.publications.analyseur_video import valider_fichier_video
from applications.publications.models import MentionJeaime, Publication, TypeMedia
from applications.utilisateurs.models import Role, Utilisateur


@pytest.fixture
def donnees_publications(db):
    gerant = Utilisateur.objects.create_user(
        courriel="gerant@kebemer.sn",
        password="Password123!",
        prenom="Moussa",
        nom="Sene",
        telephone="+221774445566",
        role=Role.RESTAURANT,
    )
    etablissement = Etablissement.objects.create(
        gerant=gerant,
        nom="Kebemer Délices",
        nom_utilisateur="kebemer_delices",
        type_etablissement=TypeEtablissement.RESTAURANT,
        statut_validation=StatutValidationPartenaire.ACTIF,
        telephone="+221774445566",
        adresse="Plateau, Dakar",
        description="Spécialités sénégalaises",
    )
    cat = CategoriePlat.objects.create(nom="Plats", slug="plats", ordre=1)
    plat = Plat.objects.create(
        etablissement=etablissement,
        categorie=cat,
        nom="Thieboudienne Penda Mbaye",
        description="Riz rouge au poisson frais et légumes",
        prix_fcfa=3500,
        est_disponible=True,
    )

    client_user = Utilisateur.objects.create_user(
        courriel="gourmand@dakar.sn",
        password="Password123!",
        prenom="Fatou",
        nom="Diop",
        telephone="+221775556677",
        role=Role.CLIENT,
    )

    return {
        "gerant": gerant,
        "etablissement": etablissement,
        "plat": plat,
        "client": client_user,
    }


@pytest.mark.django_db
def test_regle_stricte_video_300_secondes():
    """Vérifie que toute vidéo dépassant 300 secondes est strictement rejetée."""
    faux_fichier_trop_long = SimpleUploadedFile(
        name="recette_trop_longue.mp4",
        content=b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1000,
        content_type="video/mp4",
    )

    # Simuler une durée extraite de 340 secondes (> 300s)
    with patch("applications.publications.analyseur_video.extraire_duree_mp4_secondes", return_value=340.0):
        with pytest.raises(ErreurMetier) as exc:
            valider_fichier_video(faux_fichier_trop_long)

        assert "dépasse la limite autorisée de 5 minutes (300 secondes)" in str(exc.value)
        assert exc.value.code == "duree_video_trop_longue"


@pytest.mark.django_db
def test_video_conforme_autorisee():
    """Une vidéo de moins de 300 secondes doit être validée sans erreur."""
    fichier_valide = SimpleUploadedFile(
        name="presentation_plat.mp4",
        content=b"\x00\x00\x00\x20ftypisom" + b"\x00" * 1000,
        content_type="video/mp4",
    )

    with patch("applications.publications.analyseur_video.extraire_duree_mp4_secondes", return_value=85.5):
        duree = valider_fichier_video(fichier_valide)
        assert duree == 85.5


@pytest.mark.django_db
def test_fil_publications_public(donnees_publications):
    """Le fil renvoie les publications des restaurants validés au format attendu par le frontend."""
    etablissement = donnees_publications["etablissement"]
    plat = donnees_publications["plat"]

    Publication.objects.create(
        etablissement=etablissement,
        plat=plat,
        titre="Notre Thieb royal en vidéo",
        description="Venez déguster le meilleur thieb de Dakar !",
        type_media=TypeMedia.VIDEO,
        duree_secondes=45,
        est_publie=True,
    )

    client_api = APIClient()
    reponse = client_api.get("/api/publications/fil/")

    assert reponse.status_code == 200
    data = reponse.json()
    resultats = data.get("results", data)
    assert len(resultats) == 1
    item = resultats[0]
    assert item["nomRestaurant"] == "Kebemer Délices"
    assert item["nomUtilisateurRestaurant"] == "@kebemer_delices"
    assert item["descriptionAccroche"] == "Venez déguster le meilleur thieb de Dakar !"
    assert item["plat"]["nom"] == "Thieboudienne Penda Mbaye"
    assert item["typeMedia"] == "VIDEO"


@pytest.mark.django_db
def test_toggle_like_publication(donnees_publications):
    """Un utilisateur connecté peut aimer ou retirer son j'aime avec décompte exact."""
    etablissement = donnees_publications["etablissement"]
    client_user = donnees_publications["client"]

    pub = Publication.objects.create(
        etablissement=etablissement,
        titre="Yassa Poulet au feu de bois",
        type_media=TypeMedia.IMAGE,
        est_publie=True,
    )

    client_api = APIClient()
    client_api.force_authenticate(user=client_user)

    # 1. Premier clic : j'aime ajouté
    rep1 = client_api.post(f"/api/publications/{pub.id}/like/")
    assert rep1.status_code == 200
    assert rep1.json()["estAime"] is True
    assert rep1.json()["nombreJeaime"] == 1
    assert MentionJeaime.objects.filter(utilisateur=client_user, publication=pub).exists()

    # 2. Deuxième clic : j'aime retiré
    rep2 = client_api.post(f"/api/publications/{pub.id}/like/")
    assert rep2.status_code == 200
    assert rep2.json()["estAime"] is False
    assert rep2.json()["nombreJeaime"] == 0
    assert not MentionJeaime.objects.filter(utilisateur=client_user, publication=pub).exists()


@pytest.mark.django_db
def test_gestion_studio_gerant(donnees_publications):
    """Le gérant peut téléverser une publication et la supprimer dans son espace Studio."""
    gerant = donnees_publications["gerant"]
    plat = donnees_publications["plat"]

    client_api = APIClient()
    client_api.force_authenticate(user=gerant)

    fichier_video = SimpleUploadedFile(
        name="reel_plat.mp4",
        content=b"\x00" * 200,
        content_type="video/mp4",
    )

    with patch("applications.publications.analyseur_video.extraire_duree_mp4_secondes", return_value=60.0):
        rep = client_api.post(
            "/api/publications/studio/",
            {
                "titre": "Découverte en cuisine",
                "description": "Préparation minute",
                "type_media": "VIDEO",
                "fichier_media": fichier_video,
                "plat_id": plat.id,
            },
            format="multipart",
        )

    assert rep.status_code == 201
    pub_id = rep.json()["id"]

    # Suppression par le propriétaire
    rep_del = client_api.delete(f"/api/publications/studio/{pub_id}/")
    assert rep_del.status_code == 204
    assert not Publication.objects.filter(pk=pub_id).exists()


# --- Phase 8 : vues et likes comptés par le serveur --------------------------------


@pytest.mark.django_db
def test_vue_comptee_une_seule_fois_par_personne(donnees_publications):
    from django.core.cache import cache

    cache.clear()
    publication = Publication.objects.create(
        etablissement=donnees_publications["etablissement"], titre="Thieb du jour", type_media="IMAGE"
    )
    anonyme = APIClient()
    premiere = anonyme.post(f"/api/publications/{publication.id}/vue/").json()
    seconde = anonyme.post(f"/api/publications/{publication.id}/vue/").json()
    assert premiere == {"comptee": True, "nombreVues": 1}
    assert seconde == {"comptee": False, "nombreVues": 1}

    connecte = APIClient()
    connecte.force_authenticate(donnees_publications["client"])
    assert connecte.post(f"/api/publications/{publication.id}/vue/").json()["nombreVues"] == 2
    # Le compteur affiché dans le fil vient de la base
    fil = anonyme.get("/api/publications/fil/").json()
    liste = fil["results"] if isinstance(fil, dict) else fil
    assert liste[0]["nombreVues"] == 2


@pytest.mark.django_db
def test_like_sans_doublon_et_compteur_reel(donnees_publications):
    publication = Publication.objects.create(
        etablissement=donnees_publications["etablissement"], titre="Thieb du jour", type_media="IMAGE"
    )
    api = APIClient()
    api.force_authenticate(donnees_publications["client"])
    assert api.post(f"/api/publications/{publication.id}/like/").json()["nombreJeaime"] == 1
    assert api.post(f"/api/publications/{publication.id}/like/").json() == {
        "estAime": False, "nombreJeaime": 0, "message": "Mention J'aime retirée."
    }


@pytest.mark.django_db
def test_video_servie_par_morceaux_pour_iphone(settings):
    """Safari (iPhone) exige des réponses partielles « 206 » pour lire une vidéo."""
    dossier = settings.MEDIA_ROOT / "publications" / "medias"
    dossier.mkdir(parents=True)
    (dossier / "essai.mp4").write_bytes(b"0123456789" * 10)

    client = APIClient()
    partielle = client.get("/medias/publications/medias/essai.mp4", HTTP_RANGE="bytes=10-19")
    assert partielle.status_code == 206
    assert partielle["Content-Range"] == "bytes 10-19/100"
    assert partielle.content == b"0123456789"
    assert client.get("/medias/publications/medias/essai.mp4", HTTP_RANGE="bytes=500-").status_code == 416
    assert client.get("/medias/publications/medias/essai.mp4").status_code == 200
