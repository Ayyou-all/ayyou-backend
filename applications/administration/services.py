"""
Services métier pour le module d'Administration de la plateforme AYYOU.

Prend en charge :
- La modération et validation des partenaires (restaurants, livreurs)
- Le respect strict de la matrice des transitions de validation
- Le calcul des métriques et indicateurs clés de performance (KPIs)
- L'envoi automatique de notifications de décision aux partenaires
"""

from django.db import transaction
from django.db.models import Avg, Sum

from applications.commandes.models import Commande, StatutCommande
from applications.communs.choix import (
    TRANSITIONS_VALIDATION_PARTENAIRE,
    StatutValidationPartenaire,
)
from applications.communs.erreurs import ErreurMetier, TransitionInterdite
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.livraisons.models import DisponibiliteLivreur, ProfilLivreur
from applications.notifications.models import TypeNotification
from applications.notifications.services import creer_notification
from applications.utilisateurs.models import StatutDocument

STATUTS_SANCTION = {StatutValidationPartenaire.SUSPENDU, StatutValidationPartenaire.BANNI}


def valider_documents_en_attente(utilisateur) -> None:
    """Valider un dossier partenaire = déclarer conformes ses pièces encore en attente."""
    from django.utils import timezone

    utilisateur.documents.filter(statut=StatutDocument.EN_ATTENTE).update(
        statut=StatutDocument.CONFORME, date_verification=timezone.now()
    )


@transaction.atomic
def appliquer_decision_etablissement(
    etablissement: Etablissement,
    nouveau_statut: str,
    motif_decision: str = "",
    admin_user=None,
) -> Etablissement:
    """
    Applique une décision administrative sur un établissement partenaire (restaurant).
    """
    statut_actuel = etablissement.statut_validation
    transitions_possibles = TRANSITIONS_VALIDATION_PARTENAIRE.get(statut_actuel, set())

    if nouveau_statut not in transitions_possibles:
        raise TransitionInterdite(
            f"Transition de validation interdite de '{statut_actuel}' vers '{nouveau_statut}'."
        )

    etablissement.statut_validation = nouveau_statut
    etablissement.motif_decision = motif_decision
    if nouveau_statut in STATUTS_SANCTION:
        etablissement.est_ouvert = False  # un restaurant sanctionné ne reçoit plus de commandes
    etablissement.save(update_fields=["statut_validation", "motif_decision", "est_ouvert"])
    if nouveau_statut == StatutValidationPartenaire.ACTIF:
        valider_documents_en_attente(etablissement.gerant)

    # Notification du gérant
    titre = (
        "Votre établissement est désormais ACTIF !"
        if nouveau_statut == StatutValidationPartenaire.ACTIF
        else f"Mise à jour de votre compte ({nouveau_statut})"
    )
    message = (
        f"Félicitations ! Votre établissement {etablissement.nom} est maintenant visible par les clients."
        if nouveau_statut == StatutValidationPartenaire.ACTIF
        else f"Votre établissement {etablissement.nom} est passé au statut {nouveau_statut}. Motif : {motif_decision or 'Non spécifié'}."
    )

    creer_notification(
        destinataire=etablissement.gerant,
        titre=titre,
        message=message,
        type_notification=TypeNotification.VALIDATION_COMPTE,
        texte_vocal=titre,
    )

    return etablissement


@transaction.atomic
def appliquer_decision_livreur(
    profil_livreur: ProfilLivreur,
    nouveau_statut: str,
    motif_decision: str = "",
    admin_user=None,
) -> ProfilLivreur:
    """
    Applique une décision administrative sur un coursier.
    """
    statut_actuel = profil_livreur.statut_validation
    transitions_possibles = TRANSITIONS_VALIDATION_PARTENAIRE.get(statut_actuel, set())

    if nouveau_statut not in transitions_possibles:
        raise TransitionInterdite(
            f"Transition de validation interdite de '{statut_actuel}' vers '{nouveau_statut}'."
        )

    profil_livreur.statut_validation = nouveau_statut
    profil_livreur.motif_decision = motif_decision
    if nouveau_statut in STATUTS_SANCTION:
        profil_livreur.disponibilite = DisponibiliteLivreur.HORS_LIGNE
    profil_livreur.save(update_fields=["statut_validation", "motif_decision", "disponibilite"])
    if nouveau_statut == StatutValidationPartenaire.ACTIF:
        valider_documents_en_attente(profil_livreur.utilisateur)

    # Notification du coursier
    titre = (
        "Votre compte livreur est validé !"
        if nouveau_statut == StatutValidationPartenaire.ACTIF
        else f"Mise à jour de votre profil livreur ({nouveau_statut})"
    )
    message = (
        "Félicitations ! Vous pouvez maintenant passer 'En ligne' et recevoir des courses."
        if nouveau_statut == StatutValidationPartenaire.ACTIF
        else f"Votre profil livreur est passé au statut {nouveau_statut}. Motif : {motif_decision or 'Non spécifié'}."
    )

    creer_notification(
        destinataire=profil_livreur.utilisateur,
        titre=titre,
        message=message,
        type_notification=TypeNotification.VALIDATION_COMPTE,
        texte_vocal=titre,
    )

    return profil_livreur


from datetime import timedelta
from django.utils import timezone
from applications.utilisateurs.models import Role, Utilisateur


def calculer_statistiques_globales(request=None) -> dict:
    """
    Calcule les indicateurs clés de la plateforme AYYOU pour le tableau de bord Admin.
    Alimente également les graphiques réels (7 derniers jours) et les dernières validations.
    """
    commandes_payees = Commande.objects.exclude(
        statut__in=[
            StatutCommande.EN_ATTENTE_PAIEMENT,
            StatutCommande.REFUSEE_ANNULEE,
            StatutCommande.ECHEC_LIVRAISON,
        ]
    )
    total_commandes = Commande.objects.exclude(statut=StatutCommande.EN_ATTENTE_PAIEMENT).count()
    commandes_livrees = Commande.objects.filter(statut=StatutCommande.LIVREE).count()
    commandes_en_cours = Commande.objects.filter(
        statut__in=[
            StatutCommande.CREEE_EN_ATTENTE,
            StatutCommande.EN_PREPARATION,
            StatutCommande.PRETE_POUR_RETRAIT,
            StatutCommande.COURSE_ASSIGNEE,
            StatutCommande.EN_VERIFICATION,
            StatutCommande.EN_LIVRAISON,
            StatutCommande.ARRIVE_CLIENT,
        ]
    ).count()

    volume_affaires = commandes_payees.aggregate(total=Sum("total_fcfa"))["total"] or 0
    panier_moyen = int(commandes_payees.aggregate(moy=Avg("total_fcfa"))["moy"] or 0)

    total_utilisateurs = Utilisateur.objects.count()
    total_clients = Utilisateur.objects.filter(role=Role.CLIENT).count()

    total_restaurants = Etablissement.objects.count()
    restaurants_actifs = Etablissement.objects.filter(
        statut_validation=StatutValidationPartenaire.ACTIF,
    ).count()

    total_livreurs = ProfilLivreur.objects.count()
    livreurs_actifs = ProfilLivreur.objects.filter(statut_validation=StatutValidationPartenaire.ACTIF).count()
    livreurs_en_ligne = ProfilLivreur.objects.filter(disponibilite=DisponibiliteLivreur.EN_LIGNE).count()

    partenaires_en_attente = (
        Etablissement.objects.filter(statut_validation=StatutValidationPartenaire.EN_ATTENTE_VALIDATION).count()
        + ProfilLivreur.objects.filter(statut_validation=StatutValidationPartenaire.EN_ATTENTE_VALIDATION).count()
    )

    # 1. Calcul réel des commandes par jour sur les 7 derniers jours (pour la courbe SVG)
    maintenant = timezone.now()
    jours_semaine_fr = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    commandes_par_jour = []
    x_coords = [35, 135, 235, 335, 435, 535, 635]

    valeurs_jours = []
    for i in range(6, -1, -1):
        debut_jour = (maintenant - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        fin_jour = debut_jour + timedelta(days=1)
        nb_cmd = (
            Commande.objects.exclude(statut=StatutCommande.EN_ATTENTE_PAIEMENT)
            .filter(date_creation__gte=debut_jour, date_creation__lt=fin_jour)
            .count()
        )
        nom_jour = jours_semaine_fr[debut_jour.weekday()]
        valeurs_jours.append((nom_jour, debut_jour.strftime("%d %b"), nb_cmd))

    max_val = max([v[2] for v in valeurs_jours] + [1])
    for idx, (nom_jour, date_str, nb_cmd) in enumerate(valeurs_jours):
        # Y SVG entre 220 (si 0) et 65 (si pic d'activité)
        y_coord = int(220 - ((nb_cmd / max_val) * 155)) if max_val > 0 and nb_cmd > 0 else 220
        commandes_par_jour.append({
            "jour": nom_jour,
            "date": date_str,
            "valeur": nb_cmd,
            "xPourcentage": x_coords[idx] if idx < len(x_coords) else (35 + idx * 100),
            "yPourcentage": y_coord,
        })

    # 2. Dernières validations réelles (strictement les demandes en attente de modération)
    from applications.communs.outils import construire_url_absolue

    dernieres_validations = []
    etabs_en_attente = list(
        Etablissement.objects.filter(
            statut_validation=StatutValidationPartenaire.EN_ATTENTE_VALIDATION
        ).order_by("-id")[:6]
    )
    for etab in etabs_en_attente:
        logo_url = construire_url_absolue(request, etab.logo)
        dernieres_validations.append({
            "identifiant": f"rest-{etab.id}",
            "nom": etab.nom,
            "specialiteOuVehicule": etab.specialite or etab.type_etablissement or "Restaurant",
            "type": "RESTAURANT",
            "iconeOuPhoto": logo_url if logo_url else "fa-solid fa-utensils",
            "estPhoto": bool(logo_url),
            "classeFondIcone": "bg-rose-50 text-[#E51824]",
            "dateInscription": etab.date_creation.strftime("%d %b. %Y") if hasattr(etab, "date_creation") and etab.date_creation else "Récemment",
            "statut": "EN_ATTENTE",
        })

    livs_en_attente = list(
        ProfilLivreur.objects.select_related("utilisateur")
        .filter(statut_validation=StatutValidationPartenaire.EN_ATTENTE_VALIDATION)
        .order_by("-id")[:6]
    )
    for liv in livs_en_attente:
        photo_url = construire_url_absolue(request, liv.utilisateur.photo)
        dernieres_validations.append({
            "identifiant": f"liv-{liv.id}",
            "nom": liv.utilisateur.nom_complet,
            "specialiteOuVehicule": f"{liv.type_vehicule} ({liv.nom_vehicule or 'Véhicule'})",
            "type": "LIVREUR",
            "iconeOuPhoto": photo_url if photo_url else "fa-solid fa-motorcycle",
            "estPhoto": bool(photo_url),
            "classeFondIcone": "bg-amber-50 text-amber-600",
            "dateInscription": liv.utilisateur.date_creation.strftime("%d %b. %Y") if hasattr(liv, "utilisateur") and getattr(liv.utilisateur, "date_creation", None) else "Récemment",
            "statut": "EN_ATTENTE",
        })

    # 3. Top des restaurants par volume de commandes
    from django.db.models import Count
    top_restaurants_qs = Etablissement.objects.annotate(nb_commandes=Count("commandes_etablissement")).order_by("-nb_commandes")[:5]
    top_restaurants = []
    max_top_cmd = max([r.nb_commandes for r in top_restaurants_qs] + [1])
    for r in top_restaurants_qs:
        top_restaurants.append({
            "nom": r.nom,
            "commandes": r.nb_commandes,
            "pourcentageBarre": max(int((r.nb_commandes / max_top_cmd) * 100), 15) if max_top_cmd > 0 else 20,
        })

    # 4. Répartition réelle des commandes par catégorie
    from applications.commandes.models import LigneCommande
    categories_qs = (
        LigneCommande.objects.filter(plat__categorie__isnull=False)
        .values("plat__categorie__nom")
        .annotate(total=Count("id"))
        .order_by("-total")[:4]
    )
    total_lignes_cat = sum(c["total"] for c in categories_qs) or 1
    couleurs_cat = ["#E51824", "#1e293b", "#475569", "#cbd5e1"]
    commandes_par_categorie = []
    circonference = 238
    offset_courant = 0
    for idx, c in enumerate(categories_qs):
        pourcentage = int(round((c["total"] / total_lignes_cat) * 100))
        dash_len = int(round((c["total"] / total_lignes_cat) * circonference))
        commandes_par_categorie.append({
            "nom": c["plat__categorie__nom"],
            "total": c["total"],
            "pourcentage": pourcentage,
            "dasharray": f"{dash_len} {circonference}",
            "dashoffset": str(-offset_courant),
            "couleur": couleurs_cat[idx % len(couleurs_cat)],
        })
        offset_courant += dash_len

    if not commandes_par_categorie:
        commandes_par_categorie = [
            {
                "nom": "Plats locaux",
                "total": total_commandes,
                "pourcentage": 100,
                "dasharray": "238 238",
                "dashoffset": "0",
                "couleur": "#E51824",
            }
        ]

    return {
        # Formats camelCase et snake_case pour rétrocompatibilité totale
        "totalCommandes": total_commandes,
        "nombre_commandes_total": total_commandes,
        "commandesLivrees": commandes_livrees,
        "commandesActives": commandes_en_cours,
        "volumeAffairesFcfa": volume_affaires,
        "chiffre_affaires_total_fcfa": volume_affaires,
        "panierMoyenFcfa": panier_moyen,
        "totalUtilisateurs": total_utilisateurs,
        "nombre_utilisateurs_total": total_utilisateurs,
        "totalClients": total_clients,
        "totalRestaurants": total_restaurants,
        "restaurantsActifs": restaurants_actifs,
        "totalLivreurs": total_livreurs,
        "livreursActifs": livreurs_actifs,
        "livreursEnLigne": livreurs_en_ligne,
        "partenairesEnAttente": partenaires_en_attente,
        "nombre_partenaires_en_attente": partenaires_en_attente,
        "commandesParJour": commandes_par_jour,
        "commandesParCategorie": commandes_par_categorie,
        "dernieresValidations": dernieres_validations,
        "topRestaurants": top_restaurants,
    }
