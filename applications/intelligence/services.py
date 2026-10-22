"""
Services de la passerelle Django vers l'Intelligence Artificielle AYYOU.

Fournit :
1. Préparation et sérialisation des données métiers réelles (Dakar, restaurants, plats)
2. Appel sécurisé du microservice FastAPI
3. Repli dégradé gracieux (fallback déterministe) sans coupure de service
4. Richesse des réponses (cartes de plats complètes avec images et prix pour le frontend)
"""

from datetime import datetime
from django.db.models import Count, F, Sum

from applications.etablissements.models import filtre_abonnement_valide
from django.utils import timezone

from applications.catalogue.models import Plat
from applications.catalogue.serializers import SerializerPlat
from applications.commandes.models import Commande, LigneCommande, StatutCommande
from applications.etablissements.models import Etablissement
from applications.etablissements.services import obtenir_etablissement_du_gerant
from applications.publications.models import MentionJeaime

from .client_ia import appel_service_ia


def serialiser_plat_pour_ia(plat: Plat) -> dict:
    """Format plat candidat envoyé à FastAPI."""
    return {
        "id": plat.id,
        "nom": plat.nom,
        "description": plat.description or "",
        "prix_fcfa": plat.prix_fcfa,
        "restaurant_id": plat.etablissement.id,
        "nom_restaurant": plat.etablissement.nom,
        "categorie": plat.categorie.nom if plat.categorie else "",
        "nombre_likes": getattr(plat, "total_likes", 0),
        "nombre_commandes": getattr(plat, "total_commandes", 0),
    }


def recommander_plats_pour_client(utilisateur, budget_max: int = None, limite: int = 10, request=None) -> dict:
    """
    Recommandations personnalisées pour un utilisateur.
    Appelle FastAPI et replie sur un algorithme déterministe si le microservice est hors ligne.
    """
    plats_qs = (
        Plat.objects.filter(
            filtre_abonnement_valide("etablissement__"),
            est_disponible=True,
            est_archive=False,
            etablissement__statut_validation="ACTIF",
        )
        .select_related("etablissement", "categorie")
        .annotate(
            total_likes=Count("publications__mentions_jeaime", distinct=True),
            total_commandes=Count("lignes_commande", distinct=True),
        )
    )

    if budget_max:
        plats_qs = plats_qs.filter(prix_fcfa__lte=budget_max)

    plats_liste = list(plats_qs[:40])

    historique_cmd = []
    plats_aimes = []
    if utilisateur and utilisateur.is_authenticated:
        historique_cmd = list(
            LigneCommande.objects.filter(commande__client=utilisateur).values_list("plat_id", flat=True).distinct()[:20]
        )
        plats_aimes = list(
            MentionJeaime.objects.filter(utilisateur=utilisateur, publication__plat__isnull=False)
            .values_list("publication__plat_id", flat=True)
            .distinct()[:20]
        )

    heure_actuelle = timezone.localtime().hour

    payload_ia = {
        "utilisateur_id": utilisateur.id if utilisateur and utilisateur.is_authenticated else None,
        "plats": [serialiser_plat_pour_ia(p) for p in plats_liste],
        "historique_commandes_ids": historique_cmd,
        "plats_aimes_ids": plats_aimes,
        "budget_max_fcfa": budget_max,
        "heure_actuelle": heure_actuelle,
        "limite": limite,
    }

    reponse_ia = appel_service_ia("ia/recommandations/", payload_ia)

    # Récupération des objets Plat complets pour affichage frontend
    plats_dict = {p.id: p for p in plats_liste}

    if reponse_ia and "recommandations" in reponse_ia:
        plats_recommandes_data = []
        for rec in reponse_ia["recommandations"]:
            plat_obj = plats_dict.get(rec["id"])
            if plat_obj:
                donnees_plat = SerializerPlat(plat_obj, context={"request": request}).data
                donnees_plat["scorePertinence"] = rec["score_pertinence"]
                donnees_plat["raisonRecommandation"] = rec["raison_recommandation"]
                plats_recommandes_data.append(donnees_plat)

        return {
            "contexteMoment": reponse_ia.get("contexte_moment", "Recommandations du jour"),
            "plats": plats_recommandes_data,
            "source": "FASTAPI_IA",
        }

    # REPLI LOCAL (Fallback déterministe) si le service IA est indisponible
    plats_recommandes_data = []
    for p in plats_liste[:limite]:
        donnees_plat = SerializerPlat(p, context={"request": request}).data
        donnees_plat["scorePertinence"] = 75.0
        donnees_plat["raisonRecommandation"] = "Coup de cœur gourmand à Dakar"
        plats_recommandes_data.append(donnees_plat)

    return {
        "contexteMoment": "Sélection gourmande AYYOU",
        "plats": plats_recommandes_data,
        "source": "REPLI_LOCAL",
    }


def formater_donnees_plat_pour_chatbot(donnees_plat: dict, plat_obj: Plat) -> dict:
    """Enrichit les données du plat pour l'interface de cartes cliquables du chatbot."""
    url_image = donnees_plat.get("adresse_image") or ""
    donnees_plat["image_url"] = url_image
    donnees_plat["restaurant_nom"] = plat_obj.etablissement.nom if plat_obj.etablissement else ""
    donnees_plat["restaurant_id"] = plat_obj.etablissement_id
    donnees_plat["identifiant"] = str(plat_obj.id)
    return donnees_plat


import re


NOMBRES_TEXTE_BUDGET = {
    "cinq cents": 500,
    "cinq cent": 500,
    "cinq-cents": 500,
    "cinq-cent": 500,
    "six cents": 600,
    "sept cents": 700,
    "huit cents": 800,
    "neuf cents": 900,
    "mille": 1000,
    "mille cinq cents": 1500,
    "mille cinq cent": 1500,
    "deux mille": 2000,
    "deux mille cinq cents": 2500,
    "deux mille cinq cent": 2500,
    "trois mille": 3000,
    "trois mille cinq cents": 3500,
    "quatre mille": 4000,
    "cinq mille": 5000,
    "six mille": 6000,
    "sept mille": 7000,
    "huit mille": 8000,
    "neuf mille": 9000,
    "dix mille": 10000,
    "quinze mille": 15000,
    "vingt mille": 20000,
}


def extraire_budget_depuis_texte(texte: str):
    """
    Extrait avec robustesse un montant budgétaire en FCFA d'une phrase en français.
    Gère :
    - Chiffres + devises : '500 francs', '500 fcfa', '1500 cfa', '500f', '3 000 F'
    - Formulations verbales directes : 'j'ai 500', 'jai 500', 'je dispose de 1500', 'je peux mettre 2500'
    - Contraintes : 'moins de 3000', 'maximum 2500', 'max 2000', 'pas dépasser 3000', 'sous 1500'
    - Prépositions : 'pour 2000', 'avec 1500', 'de 3000', 'à 2500'
    - Mots en toutes lettres : 'cinq cents francs', 'mille cinq cents', 'deux mille'
    - Formats k/mille : '2,5 mille' -> 2500, '2.5 mille' -> 2500
    - Séparateurs d'espace et de points : '1 500', '3.000'
    """
    if not texte:
        return None
    texte_clean = texte.lower().strip()

    # 1. Format '2,5 mille'
    match_k = re.search(r"(\d+(?:[,\.]\d+)?)\s*mille", texte_clean)
    if match_k:
        val_str = match_k.group(1).replace(",", ".")
        try:
            return int(float(val_str) * 1000)
        except ValueError:
            pass

    # 2. Mots en toutes lettres
    for nom_texte, valeur in sorted(NOMBRES_TEXTE_BUDGET.items(), key=lambda x: -len(x[0])):
        if nom_texte in texte_clean:
            return valeur

    # 3. Motifs regex
    motifs = [
        r"(\d+[\s\.]?\d*)\s*(?:fcfa|cfa|frs|francs?|f\b)",
        r"(?:budget|budjet|tarif|somme)(?:\s*(?:de|max|maximum|environ|égal|egal|:|=))?\s*(\d+[\s\.]?\d*)",
        r"(?:moins\s+de|maximum|max|ne\s+pas\s+dépasser|pas\s+dépasser|sous|inférieur\s+à)\s*(\d+[\s\.]?\d*)",
        r"(?:j['’]?\s*ai|jai|dispose\s+de|peux\s+mettre|mettre\s+au\s+max)\s*(\d+[\s\.]?\d*)",
        r"(?:pour|avec|de|à|a)\s*(\d+[\s\.]?\d*)\s*(?:fcfa|cfa|frs|francs?|f\b)?",
        r"\b(\d{3,5})\b",
    ]

    for motif in motifs:
        match = re.search(motif, texte_clean)
        if match:
            chiffres = re.sub(r"[\s\.]", "", match.group(1))
            try:
                val = int(chiffres)
                if 200 <= val <= 100000:
                    return val
            except ValueError:
                continue

    return None


def transcrire_fichier_audio(fichier_octets: bytes, nom_fichier: str = "audio.webm") -> dict:
    """Relaye le fichier audio vers le microservice IA Whisper."""
    import httpx
    from django.conf import settings
    url = f"{settings.SERVICE_IA_URL.rstrip('/')}/ia/transcription/"
    headers = {
        "X-AYYOU-IA-KEY": settings.SERVICE_IA_CLE_INTERNE,
    }
    try:
        fichiers = {"fichier": (nom_fichier, fichier_octets, "audio/webm")}
        with httpx.Client(timeout=120.0) as client:
            res = client.post(url, files=fichiers, headers=headers)
            if res.status_code == 200:
                return res.json()
            return {"succes": False, "texte": "", "message": res.text}
    except Exception as exc:
        return {"succes": False, "texte": "", "message": str(exc)}


def repondre_au_message_chatbot(
    message_texte: str,
    budget_fcfa: int = None,
    quartier: str = None,
    historique: list = None,
    request=None,
) -> dict:
    """
    Chatbot culinaire interactif sous contrainte budgétaire.
    Garantit le respect strict du budget (prix_plat <= budget_fcfa).
    """
    # 1. Extraction tolérante et robuste du budget
    if not budget_fcfa:
        budget_fcfa = extraire_budget_depuis_texte(message_texte)

    # Si l'utilisateur demande "moins cher" sans préciser de nouveau montant, on déduit à partir de l'historique
    if not budget_fcfa and historique and any(terme in message_texte.lower() for terme in ["moins cher", "plus abordable", "plus économique", "plus economique"]):
        for h in reversed(historique):
            txt = h.get("contenu") or h.get("content") or h.get("texte") or ""
            b_prec = extraire_budget_depuis_texte(txt)
            if b_prec:
                budget_fcfa = int(b_prec * 0.8)
                break

    plats_qs = (
        Plat.objects.filter(
            filtre_abonnement_valide("etablissement__"),
            est_disponible=True,
            est_archive=False,
            etablissement__statut_validation="ACTIF",
        )
        .select_related("etablissement", "categorie")
        .annotate(
            total_likes=Count("publications__mentions_jeaime", distinct=True),
            total_commandes=Count("lignes_commande", distinct=True),
        )
    )

    # Filtrage strict au niveau base de données si budget présent
    if budget_fcfa:
        plats_qs = plats_qs.filter(prix_fcfa__lte=budget_fcfa)

    plats_candidats = list(plats_qs[:30])
    plats_dict = {p.id: p for p in plats_candidats}

    payload = {
        "message": message_texte,
        "budget_fcfa": budget_fcfa,
        "quartier": quartier,
        "historique": historique or [],
        "plats_disponibles": [serialiser_plat_pour_ia(p) for p in plats_candidats],
    }

    reponse_ia = appel_service_ia("ia/chatbot/", payload)

    if reponse_ia and "texte_reponse" in reponse_ia:
        budget_ia = reponse_ia.get("budget_detecte_fcfa") or budget_fcfa
        ids = reponse_ia.get("plats_suggeres_ids", [])
        plats_suggeres = []
        for pid in ids:
            if pid in plats_dict:
                plat_obj = plats_dict[pid]
                # Double vérification stricte : aucun plat ne doit dépasser le budget
                if budget_ia and plat_obj.prix_fcfa > budget_ia:
                    continue
                data = SerializerPlat(plat_obj, context={"request": request}).data
                data = formater_donnees_plat_pour_chatbot(data, plat_obj)
                plats_suggeres.append(data)

        return {
            "reponse_texte": reponse_ia["texte_reponse"],
            "texteReponse": reponse_ia["texte_reponse"],
            "cartes_plats": plats_suggeres,
            "plats": plats_suggeres,
            "budget_detecte_fcfa": budget_ia,
            "budgetRespecte": reponse_ia.get("budget_respecte", True),
            "intention": reponse_ia.get("intention_detectee", "SUGGESTION"),
            "source": "FASTAPI_IA",
        }

    # REPLI LOCAL (Fallback déterministe avec garantie stricte du budget)
    if budget_fcfa:
        # Aucun plat ne doit dépasser le budget
        plats_candidats = [p for p in plats_candidats if p.prix_fcfa <= budget_fcfa]

    if budget_fcfa and not plats_candidats:
        msg = (
            f"Avec un budget de {budget_fcfa:,} FCFA, je n'ai pas trouvé de plat disponible dans cette gamme de prix "
            "pour le moment. Souhaites-tu que je recherche les options les moins chères ou préfères-tu augmenter ton budget ?"
        )
        return {
            "reponse_texte": msg,
            "texteReponse": msg,
            "cartes_plats": [],
            "plats": [],
            "budget_detecte_fcfa": budget_fcfa,
            "budgetRespecte": False,
            "intention": "AUCUN_PLAT_SOUS_BUDGET",
            "source": "REPLI_LOCAL",
        }

    plats_choisis = plats_candidats[:3]
    plats_suggeres = []
    for p in plats_choisis:
        data = SerializerPlat(p, context={"request": request}).data
        data = formater_donnees_plat_pour_chatbot(data, p)
        plats_suggeres.append(data)

    msg = (
        f"Voici d'excellents plats sous votre budget de {budget_fcfa:,} FCFA disponibles immédiatement à Dakar :"
        if budget_fcfa
        else "Voici notre sélection des spécialités les plus appréciées à Dakar :"
    )

    return {
        "reponse_texte": msg,
        "texteReponse": msg,
        "cartes_plats": plats_suggeres,
        "plats": plats_suggeres,
        "budget_detecte_fcfa": budget_fcfa,
        "budgetRespecte": True,
        "intention": "SUGGESTION",
        "source": "REPLI_LOCAL",
    }



def analyser_recherche_vocale(texte: str) -> dict:
    """
    Recherche vocale : le service IA transforme la phrase dictée en filtres
    (spécialités, budget, quartier, tri par prix, restaurants ouverts).
    Seuls les quartiers où se trouvent des restaurants actifs sont reconnus.
    """
    quartiers = list(
        Etablissement.objects.filter(statut_validation="ACTIF")
        .exclude(quartier_ville="")
        .values_list("quartier_ville", flat=True)
        .distinct()
    )
    reponse_ia = appel_service_ia("ia/recherche-vocale/", {"texte": texte, "quartiers_connus": quartiers})
    if reponse_ia and "termes_recherche" in reponse_ia:
        return {**reponse_ia, "texte": texte, "source": "FASTAPI_IA"}

    # REPLI LOCAL : sans le service IA, on cherche simplement les mots significatifs de la phrase.
    mots = [mot.strip(".,;:!?'\"").lower() for mot in texte.split()]
    return {
        "texte": texte,
        "texte_normalise": texte.lower(),
        "specialites": [],
        "termes_recherche": [],
        "mots_libres": [mot for mot in mots if len(mot) >= 4 and not mot.isdigit()],
        "budget_max_fcfa": None,
        "quartier": None,
        "tri": None,
        "ouvert_seulement": False,
        "source": "REPLI_LOCAL",
    }


# En dessous de ces seuils, on n'affiche pas de prévision ni d'analyse : elles seraient fausses.
MINIMUM_COMMANDES_PREVISIONS = 20  # sur les 4 dernières semaines
MINIMUM_COMMANDES_RAPPORT = 5  # sur les 7 derniers jours
MESSAGE_DONNEES_INSUFFISANTES = "Données insuffisantes pour produire une prévision fiable."
SEMAINES_HISTORIQUE = 4


def obtenir_previsions_etablissement(utilisateur) -> dict:
    """
    Affluence attendue aujourd'hui, heure par heure, calculée sur les 4 derniers mêmes jours
    de la semaine (ex. : les 4 derniers vendredis). Pas de profil inventé.
    """
    from applications.commandes.statistiques import STATUTS_NON_COMPTES

    etablissement = obtenir_etablissement_du_gerant(utilisateur)
    jour_cible = timezone.localtime().weekday()
    commandes = Commande.objects.filter(
        etablissement=etablissement,
        date_creation__gte=timezone.now() - timezone.timedelta(weeks=SEMAINES_HISTORIQUE),
    ).exclude(statut__in=STATUTS_NON_COMPTES)

    if commandes.count() < MINIMUM_COMMANDES_PREVISIONS:
        return {
            "restaurant_id": etablissement.id,
            "nom_restaurant": etablissement.nom,
            "donnees_suffisantes": False,
            "message": MESSAGE_DONNEES_INSUFFISANTES,
            "previsions_par_heure": [],
            "conseils_organisation": [],
        }

    ventes = {}
    for commande in commandes:
        moment = timezone.localtime(commande.date_creation)
        cle = (moment.weekday(), moment.hour)
        ventes.setdefault(cle, {"quantite_commandes": 0, "chiffre_affaires_fcfa": 0})
        ventes[cle]["quantite_commandes"] += 1
        ventes[cle]["chiffre_affaires_fcfa"] += commande.sous_total_fcfa

    # Calcul prédictif direct dans Django (indépendant du microservice IA)
    previsions = [
        {"heure": heure, "commandes_estimees": round(valeurs["quantite_commandes"] / SEMAINES_HISTORIQUE, 1)}
        for (jour, heure), valeurs in sorted(ventes.items())
        if jour == jour_cible
    ]
    pic = max(previsions, key=lambda p: p["commandes_estimees"], default=None)
    return {
        "restaurant_id": etablissement.id,
        "nom_restaurant": etablissement.nom,
        "donnees_suffisantes": True,
        "previsions_par_heure": previsions,
        "heure_de_pointe": f"{pic['heure']}h-{pic['heure'] + 1}h" if pic else "",
        "conseils_organisation": [
            "Préparez vos ingrédients 30 minutes avant le coup de feu.",
            "Assurez-vous d'avoir suffisamment d'emballages pour la livraison.",
        ],
        "source": "CALCUL_LOCAL",
    }


def generer_rapport_hebdo_etablissement(utilisateur) -> dict:
    """Rapport de la semaine écoulée, construit uniquement sur les vraies commandes."""
    from applications.commandes.statistiques import meilleures_ventes, resume_periode

    etablissement = obtenir_etablissement_du_gerant(utilisateur)
    fin = timezone.now()
    debut = fin - timezone.timedelta(days=7)
    resume = resume_periode(etablissement, debut, fin)

    if resume["commandes"] < MINIMUM_COMMANDES_RAPPORT:
        return {
            "restaurant_id": etablissement.id,
            "donnees_suffisantes": False,
            "message": MESSAGE_DONNEES_INSUFFISANTES,
            "statistiques": resume,
        }

    plats_vendus = meilleures_ventes(etablissement, debut, fin)
    # Calcul direct du rapport d'activité dans Django (100% autonome et immédiat)
    return {
        "restaurant_id": etablissement.id,
        "donnees_suffisantes": True,
        "titre_rapport": f"Bilan des 7 derniers jours — {etablissement.nom}",
        "resume_executif": (
            f"{resume['commandes']} commandes pour {resume['chiffre_affaires_fcfa']:,} FCFA "
            f"(panier moyen {resume['panier_moyen_fcfa']:,} FCFA)."
        ).replace(",", " "),
        "plat_star": plats_vendus[0]["nom"] if plats_vendus else "",
        "panier_moyen_fcfa": resume["panier_moyen_fcfa"],
        "points_forts": [f"Plat le plus vendu : {plats_vendus[0]['nom']}" if plats_vendus else "Activité régulière"],
        "recommandations_actionnables": ["Poursuivre la promotion des spécialités phares aux heures de pointe"],
        "statistiques": resume,
        "source": "CALCUL_LOCAL",
    }
