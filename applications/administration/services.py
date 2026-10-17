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
            "dateInscription": etab.date_creation.strftime("%d %b. %Y") if hasattr(etab, "date_creation") and etab.date_creation else "",
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
            "dateInscription": liv.utilisateur.date_creation.strftime("%d %b. %Y") if hasattr(liv, "utilisateur") and getattr(liv.utilisateur, "date_creation", None) else "",
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
        # Argent : ce qui revient à la plateforme et ce qui reste à rembourser
        "commissionPlateformeFcfa": commandes_payees.aggregate(total=Sum("commission_plateforme_fcfa"))["total"] or 0,
        "commandesARembourser": sum(
            1
            for c in Commande.objects.filter(
                statut__in=[StatutCommande.REFUSEE_ANNULEE, StatutCommande.ECHEC_LIVRAISON]
            ).prefetch_related("tentatives_paiement")
            if paiement_a_rembourser(c)
        ),
        "echecsLivraison": Commande.objects.filter(statut=StatutCommande.ECHEC_LIVRAISON).count(),
        "commandesEnAttente": Commande.objects.filter(
            statut__in=[StatutCommande.EN_ATTENTE_PAIEMENT, StatutCommande.CREEE_EN_ATTENTE]
        ).count(),
        "commandesAnnulees": Commande.objects.filter(
            statut__in=[StatutCommande.REFUSEE_ANNULEE, StatutCommande.ECHEC_LIVRAISON]
        ).count(),
    }



# ---------------------------------------------------------------------------
# Actions du support sur une commande (toutes tracées dans l'historique)
# ---------------------------------------------------------------------------


def paiement_a_rembourser(commande) -> bool:
    """Commande terminée sans livraison mais dont un paiement confirmé n'a pas été remboursé."""
    from applications.paiements.models import StatutPaiement

    return commande.statut in (StatutCommande.REFUSEE_ANNULEE, StatutCommande.ECHEC_LIVRAISON) and any(
        tentative.statut == StatutPaiement.CONFIRME for tentative in commande.tentatives_paiement.all()
    )


def admin_annuler_commande(commande, admin, motif: str):
    """
    Annule une commande pas encore partie chez le client, libère le livreur éventuel
    et rembourse le client. Une commande en route se termine par la livraison ou un échec déclaré.
    """
    from applications.commandes.services import annuler_et_rembourser
    from applications.communs.erreurs import ErreurMetier
    from applications.livraisons.models import Livraison

    if not motif.strip():
        raise ErreurMetier("Le motif est obligatoire.", code="motif_obligatoire")
    if commande.statut in (StatutCommande.EN_LIVRAISON, StatutCommande.ARRIVE_CLIENT):
        raise ErreurMetier(
            "La commande est en route : attendez la livraison ou l'échec déclaré par le livreur, puis remboursez.",
            code="commande_en_route",
        )
    livraison = Livraison.objects.filter(commande=commande).select_related("livreur").first()
    commande = annuler_et_rembourser(commande, admin, motif=motif.strip(), commentaire=f"Annulation support : {motif.strip()}")
    if livraison is not None:
        livraison.livreur.disponibilite = DisponibiliteLivreur.EN_LIGNE
        livraison.livreur.save(update_fields=["disponibilite"])
    return commande


def admin_rembourser_commande(commande, admin) -> bool:
    """Relance le remboursement d'une commande annulée ou en échec (si PayTech avait échoué)."""
    from applications.commandes.models import HistoriqueStatutCommande
    from applications.communs.erreurs import ErreurMetier
    from applications.notifications.services import creer_notification
    from applications.paiements.services import rembourser_paiements_commande

    if not paiement_a_rembourser(commande):
        raise ErreurMetier("Aucun paiement à rembourser pour cette commande.", code="rien_a_rembourser")
    rembourse = rembourser_paiements_commande(commande)
    HistoriqueStatutCommande.objects.create(
        commande=commande, ancien_statut=commande.statut, nouveau_statut=commande.statut, auteur=admin,
        commentaire="Remboursement effectué par le support." if rembourse else "Remboursement refusé par PayTech.",
    )
    if not rembourse:
        raise ErreurMetier("PayTech a refusé le remboursement. Réessayez plus tard ou remboursez manuellement.", code="remboursement_echoue")
    creer_notification(
        destinataire=commande.client,
        titre="Remboursement effectué",
        message=f"Les {commande.total_fcfa} FCFA de la commande {commande.reference} vous ont été remboursés.",
        reference_commande=commande.reference,
    )
    return True


def admin_assigner_livreur(commande, admin, livreur_id: int):
    """Assigne à la main une commande prête à un livreur validé, en ligne et libre."""
    from applications.communs.erreurs import ErreurMetier
    from applications.livraisons.services import accepter_mission_livraison
    from applications.notifications.services import creer_notification

    profil = ProfilLivreur.objects.filter(pk=livreur_id).select_related("utilisateur").first()
    if profil is None:
        raise ErreurMetier("Livreur introuvable.", code="livreur_introuvable")
    livraison = accepter_mission_livraison(commande, profil, assigne_par=admin)
    creer_notification(
        destinataire=profil.utilisateur,
        titre=f"Course {commande.reference} assignée",
        message=f"L'administration vous a assigné la commande de {commande.etablissement.nom}. Ouvrez l'application.",
        reference_commande=commande.reference,
    )
    return livraison


def admin_retirer_livreur(commande, admin, motif: str):
    """Retire le livreur (avant la remise au restaurant) : la course est reproposée aux autres."""
    from applications.communs.erreurs import ErreurMetier
    from applications.livraisons.models import Livraison
    from applications.livraisons.services import annuler_course_par_livreur
    from applications.notifications.services import creer_notification

    livraison = Livraison.objects.filter(commande=commande).select_related("livreur__utilisateur").first()
    if livraison is None:
        raise ErreurMetier("Aucun livreur assigné à cette commande.", code="aucun_livreur")
    annuler_course_par_livreur(livraison.livreur, motif, auteur=admin)
    creer_notification(
        destinataire=livraison.livreur.utilisateur,
        titre=f"Course {commande.reference} retirée",
        message=f"L'administration vous a retiré cette course. Motif : {motif.strip()}",
        reference_commande=commande.reference,
    )
    commande.refresh_from_db()
    return commande


def admin_debloquer_livraison(commande, admin):
    """
    Après 5 PIN erronés la livraison est bloquée. Le support a vérifié avec le client
    (appel téléphonique) : il remet le compteur à zéro pour que le livreur réessaie.
    Si la remise est impossible, le livreur déclare un échec et le support rembourse.
    """
    from applications.commandes.models import HistoriqueStatutCommande
    from applications.communs.erreurs import ErreurMetier
    from applications.livraisons.models import Livraison
    from applications.livraisons.services import livraison_est_bloquee

    livraison = Livraison.objects.select_for_update().filter(commande=commande).select_related("livreur__utilisateur").first()
    if livraison is None or not livraison_est_bloquee(livraison):
        raise ErreurMetier("Cette livraison n'est pas bloquée.", code="livraison_non_bloquee")
    livraison.essais_code_echoues = 0
    livraison.save(update_fields=["essais_code_echoues"])
    HistoriqueStatutCommande.objects.create(
        commande=commande, ancien_statut=commande.statut, nouveau_statut=commande.statut, auteur=admin,
        commentaire="Livraison débloquée par le support après trop de codes PIN erronés.",
    )
    creer_notification(
        destinataire=livraison.livreur.utilisateur,
        titre=f"Livraison {commande.reference} débloquée",
        message="Le support a débloqué la livraison : demandez à nouveau le code PIN au client.",
        reference_commande=commande.reference,
    )
