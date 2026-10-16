"""
Services d'authentification : création de compte et émission des jetons JWT.

Appelés par `authentification/views.py`. Aucune logique HTTP ici.
"""

import logging
import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger("ayyou")

from applications.communs.erreurs import ErreurMetier
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.etablissements.services import generer_nom_utilisateur_unique
from applications.livraisons.models import ProfilLivreur
from applications.utilisateurs.models import (
    DocumentJustificatif,
    Role,
    StatutDocument,
    TypeDocument,
    Utilisateur,
)

from .models import CodeVerificationEmail, TypeActionVerification


@transaction.atomic
def creer_compte(donnees: dict) -> Utilisateur:
    """
    Crée l'utilisateur et, selon le rôle, son établissement ou son profil livreur,
    ainsi que les pièces justificatives officielles (RCCM, Permis, etc.).

    Tout est créé dans UNE transaction : si la création échoue, aucun compte partiel.
    Les partenaires démarrent en EN_ATTENTE_VALIDATION (sas obligatoire).
    """
    role = donnees["role"]
    utilisateur = Utilisateur.objects.create_user(
        courriel=donnees["courriel"],
        password=donnees["mot_de_passe"],
        prenom=donnees["prenom"].strip(),
        nom=donnees["nom"].strip(),
        telephone=donnees["telephone"],
        role=role,
        adresse=donnees.get("adresse", ""),
    )
    if donnees.get("photo"):
        utilisateur.photo = donnees["photo"]
        utilisateur.save(update_fields=["photo"])

    if role == Role.RESTAURANT:
        nom_etablissement = donnees["nom_etablissement"].strip()
        etab_kwargs = {
            "gerant": utilisateur,
            "type_etablissement": TypeEtablissement.RESTAURANT,
            "nom": nom_etablissement,
            "nom_utilisateur": generer_nom_utilisateur_unique(nom_etablissement),
            "adresse": donnees.get("adresse", ""),
            "telephone": utilisateur.telephone,
        }
        if donnees.get("logo"):
            etab_kwargs["logo"] = donnees["logo"]
        if donnees.get("couverture"):
            etab_kwargs["couverture"] = donnees["couverture"]

        Etablissement.objects.create(**etab_kwargs)

        # Enregistrement du document justificatif officiel (RCCM, NINEA, etc.)
        if donnees.get("document_justificatif"):
            type_doc = donnees.get("document_type") or TypeDocument.RCCM
            DocumentJustificatif.objects.create(
                proprietaire=utilisateur,
                type_document=type_doc,
                fichier=donnees["document_justificatif"],
                statut=StatutDocument.EN_ATTENTE,
            )

    elif role == Role.LIVREUR:
        ProfilLivreur.objects.create(
            utilisateur=utilisateur,
            type_vehicule=donnees.get("type_vehicule") or "MOTO",
            nom_vehicule=donnees.get("nom_vehicule", "").strip(),
            immatriculation=donnees.get("immatriculation", "").strip(),
            zone_principale=donnees.get("zone_principale", "").strip(),
        )

        # Enregistrement des documents du livreur (permis recto/verso)
        if donnees.get("permis_recto"):
            DocumentJustificatif.objects.create(
                proprietaire=utilisateur,
                type_document=TypeDocument.PERMIS_CONDUIRE,
                fichier=donnees["permis_recto"],
                statut=StatutDocument.EN_ATTENTE,
            )
        if donnees.get("permis_verso"):
            DocumentJustificatif.objects.create(
                proprietaire=utilisateur,
                type_document=TypeDocument.PERMIS_CONDUIRE,
                fichier=donnees["permis_verso"],
                statut=StatutDocument.EN_ATTENTE,
            )
        if donnees.get("document_justificatif"):
            DocumentJustificatif.objects.create(
                proprietaire=utilisateur,
                type_document=TypeDocument.CNI,
                fichier=donnees["document_justificatif"],
                statut=StatutDocument.EN_ATTENTE,
            )

    return utilisateur


def authentifier(identifiant: str, mot_de_passe: str) -> Utilisateur:
    """Retrouve le compte par courriel ou téléphone puis vérifie le mot de passe."""
    identifiant = identifiant.strip()
    compte = Utilisateur.objects.filter(
        Q(courriel__iexact=identifiant) | Q(telephone=identifiant.replace(" ", ""))
    ).first()
    # Message volontairement identique dans les deux cas : on ne révèle pas si le compte existe.
    message = "Identifiant ou mot de passe incorrect."
    if compte is None:
        raise ErreurMetier(message, code="identifiants_invalides")
    utilisateur = authenticate(courriel=compte.courriel, password=mot_de_passe)
    if utilisateur is None:
        if not compte.is_active and compte.check_password(mot_de_passe):
            raise ErreurMetier("Ce compte est désactivé. Contactez le support AYYOU.", code="compte_desactive")
        raise ErreurMetier(message, code="identifiants_invalides")
    return utilisateur


def generer_jetons(utilisateur: Utilisateur) -> dict:
    """Crée la paire de jetons JWT (accès court + rafraîchissement)."""
    jeton_rafraichissement = RefreshToken.for_user(utilisateur)
    jeton_rafraichissement["role"] = utilisateur.role  # information de confort, jamais utilisée seule pour autoriser
    return {
        "jeton_acces": str(jeton_rafraichissement.access_token),
        "jeton_rafraichissement": str(jeton_rafraichissement),
    }


def generer_et_envoyer_code_verification(courriel: str, type_action: str = "INSCRIPTION") -> dict:
    """
    Génère un code éphémère à 6 chiffres et l'envoie réellement par e-mail via SMTP.
    """
    courriel = courriel.strip().lower()
    # Invalide les anciens codes actifs pour cette adresse
    CodeVerificationEmail.objects.filter(
        courriel=courriel,
        type_action=type_action,
        est_utilise=False
    ).update(est_utilise=True)

    # Génération sécurisée d'un code à 6 chiffres
    code = f"{secrets.randbelow(900000) + 100000}"
    # Le code est valable 2 minutes (avec une marge de 30 secondes pour compenser la latence réseau)
    date_expiration = timezone.now() + timedelta(minutes=2, seconds=30)

    CodeVerificationEmail.objects.create(
        courriel=courriel,
        code=code,
        type_action=type_action,
        date_expiration=date_expiration,
    )

    sujet = f"Votre code de vérification AYYOU : {code}"
    corps_texte = f"""Bonjour,

Voici votre code de vérification pour votre inscription sur la plateforme AYYOU :

    {code}

Ce code est valable pendant 2 minutes. Pour votre sécurité, ne le transmettez à personne.

Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet e-mail.

L'équipe AYYOU 🇸🇳
Plateforme culinaire et de livraison à Dakar
"""
    corps_html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 28px; border: 1px solid #e2e8f0; border-radius: 20px; background-color: #ffffff; color: #1e293b;">
        <div style="text-align: center; margin-bottom: 24px;">
            <h1 style="color: #E51824; font-size: 26px; margin: 0; font-weight: 900; letter-spacing: -0.5px;">AYYOU 🇸🇳</h1>
            <p style="color: #64748b; font-size: 13px; margin: 4px 0 0 0;">Sécurité et vérification de votre compte</p>
        </div>
        <div style="background-color: #f8fafc; border: 1px solid #f1f5f9; border-radius: 16px; padding: 24px; text-align: center; margin: 20px 0;">
            <p style="color: #475569; font-size: 14px; margin: 0 0 12px 0;">Votre code de vérification à 6 chiffres :</p>
            <div style="font-size: 38px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 12px 0; font-family: monospace; background: #ffffff; padding: 12px; border-radius: 12px; border: 1px dashed #cbd5e1; display: inline-block;">
                {code}
            </div>
            <p style="color: #94a3b8; font-size: 12px; margin: 12px 0 0 0;">⏱️ Ce code expire dans <strong>2 minutes</strong>.</p>
        </div>
        <p style="color: #64748b; font-size: 12px; line-height: 1.5; margin: 20px 0 0 0; text-align: center;">
            Si vous n'avez pas demandé ce code sur AYYOU, ignorez simplement cet e-mail en toute sérénité.
        </p>
    </div>
    """

    try:
        if "console" in settings.EMAIL_BACKEND.lower():
            logger.warning(
                f"[CODE VERIFICATION - MODE CONSOLE] Destinataire : {courriel} | CODE : {code} | "
                "Mode console actif (AYYOU_EMAIL_HOST_USER non configuré ou .env non chargé)."
            )
        send_mail(
            subject=sujet,
            message=corps_texte,
            html_message=corps_html,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[courriel],
            fail_silently=False,
        )
        if "console" not in settings.EMAIL_BACKEND.lower():
            logger.info(f"[CODE VERIFICATION - SMTP REEL] Code de vérification envoyé à {courriel}")
    except Exception as exc:
        logger.error(f"Échec envoi code email SMTP à {courriel} : {exc}", exc_info=True)
        detail_erreur = str(exc)
        if "Authentication" in detail_erreur or "535" in detail_erreur or "Username and Password not accepted" in detail_erreur:
            msg = "Erreur d'authentification SMTP Google (Code 535). Veuillez générer et configurer un mot de passe d'application Google (16 caractères sans espaces)."
        elif "timed out" in detail_erreur.lower() or "timeout" in detail_erreur.lower():
            msg = "Délai de connexion SMTP dépassé. Le port 587 est potentiellement filtré par le pare-feu du VPS LWS. Passez sur le port 465 avec SSL dans votre .env."
        elif "connection refused" in detail_erreur.lower():
            msg = "Connexion refusée vers le serveur SMTP Google. Vérifiez le pare-feu de votre serveur VPS."
        elif "sender address" in detail_erreur.lower() or "553" in detail_erreur:
            msg = f"Adresse expéditeur rejetée par Google ({settings.DEFAULT_FROM_EMAIL}). Elle doit correspondre à votre compte Gmail."
        else:
            msg = f"Impossible d'envoyer l'e-mail ({exc.__class__.__name__} : {exc}). Vérifiez les paramètres SMTP de votre serveur."
        raise ErreurMetier(msg, code="echec_envoi_email")

    return {
        "succes": True,
        "message": f"Code de vérification envoyé avec succès à {courriel}.",
        "expiration_minutes": 2,
    }


def verifier_code_email(courriel: str, code: str, type_action: str = "INSCRIPTION") -> bool:
    """
    Vérifie le code de vérification saisi par l'utilisateur.
    Lève une ErreurMetier explicite si expiré, erroné ou déjà consommé.
    """
    courriel = courriel.strip().lower()
    code = code.strip()

    dernier_code = (
        CodeVerificationEmail.objects.filter(courriel=courriel, type_action=type_action)
        .order_by("-date_creation")
        .first()
    )

    if not dernier_code or not dernier_code.est_valide:
        raise ErreurMetier(
            "Le code de vérification est expiré ou invalide. Veuillez demander un nouveau code.",
            code="code_expire",
        )

    if dernier_code.code != code:
        dernier_code.enregistrer_echec()
        raise ErreurMetier("Le code saisi est incorrect.", code="code_incorrect")

    dernier_code.marquer_utilise()
    return True

