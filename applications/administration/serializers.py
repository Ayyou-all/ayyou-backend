"""
Serializers pour les actions et le tableau de bord d'administration AYYOU.
"""

from rest_framework import serializers

from applications.communs.choix import StatutValidationPartenaire
from applications.etablissements.models import Etablissement
from applications.livraisons.models import ProfilLivreur
from applications.utilisateurs.serializers import SerializerDocumentJustificatif


class SerializerDecisionPartenaire(serializers.Serializer):
    """Validation ou changement de statut d'un partenaire par l'administrateur."""

    nouveau_statut = serializers.ChoiceField(choices=StatutValidationPartenaire.choices)
    motif_decision = serializers.CharField(required=False, allow_blank=True, default="")


class SerializerEtablissementModeration(serializers.ModelSerializer):
    """Présentation d'un établissement pour modération et gestion globale superadmin."""

    documents = serializers.SerializerMethodField()
    nomGerant = serializers.CharField(source="gerant.nom_complet", read_only=True)
    emailGerant = serializers.CharField(source="gerant.courriel", read_only=True)
    telephoneGerant = serializers.CharField(source="gerant.telephone", read_only=True)
    totalCommandes = serializers.SerializerMethodField()
    noteMoyenne = serializers.SerializerMethodField()

    platsMenu = serializers.SerializerMethodField()

    class Meta:
        model = Etablissement
        fields = [
            "id",
            "nom",
            "type_etablissement",
            "nom_utilisateur",
            "telephone",
            "adresse",
            "specialite",
            "quartier_ville",
            "est_ouvert",
            "statut_validation",
            "motif_decision",
            "date_creation",
            "nomGerant",
            "emailGerant",
            "telephoneGerant",
            "totalCommandes",
            "noteMoyenne",
            "documents",
            "platsMenu",
        ]

    def get_platsMenu(self, obj):
        return [
            {
                "nom": p.nom,
                "description": p.description or "Plat signature préparé avec des produits frais.",
                "prix": p.prix_fcfa,
            }
            for p in obj.plats.filter(est_archive=False)[:10]
        ]

    def get_documents(self, obj):
        if not obj.gerant:
            return []
        docs = obj.gerant.documents.all()
        return SerializerDocumentJustificatif(docs, many=True, context=self.context).data

    def get_totalCommandes(self, obj):
        return obj.commandes_etablissement.count()

    def get_noteMoyenne(self, obj):
        return 4.8


class SerializerLivreurModeration(serializers.ModelSerializer):
    """Présentation d'un coursier pour modération et gestion globale superadmin."""

    documents = serializers.SerializerMethodField()
    nomComplet = serializers.CharField(source="utilisateur.nom_complet", read_only=True)
    email = serializers.EmailField(source="utilisateur.courriel", read_only=True)
    telephone = serializers.CharField(source="utilisateur.telephone", read_only=True)
    dateInscription = serializers.DateTimeField(source="utilisateur.date_creation", read_only=True)
    totalLivraisons = serializers.SerializerMethodField()
    noteMoyenne = serializers.SerializerMethodField()

    class Meta:
        model = ProfilLivreur
        fields = [
            "id",
            "type_vehicule",
            "nom_vehicule",
            "immatriculation",
            "zone_principale",
            "disponibilite",
            "statut_validation",
            "motif_decision",
            "dateInscription",
            "nomComplet",
            "email",
            "telephone",
            "totalLivraisons",
            "noteMoyenne",
            "documents",
        ]

    def get_documents(self, obj):
        if not obj.utilisateur:
            return []
        docs = obj.utilisateur.documents.all()
        return SerializerDocumentJustificatif(docs, many=True, context=self.context).data

    def get_totalLivraisons(self, obj):
        return obj.missions_livraison.count()

    def get_noteMoyenne(self, obj):
        return 4.9


class SerializerArticleCommandeAdmin(serializers.Serializer):
    nom = serializers.CharField()
    quantite = serializers.IntegerField()
    prixUnitaire = serializers.IntegerField()


class SerializerCommandeAdministration(serializers.Serializer):
    """Présentation complète d'une commande pour la supervision Superadmin."""

    id = serializers.IntegerField()
    identifiantCommande = serializers.SerializerMethodField()
    clientNom = serializers.SerializerMethodField()
    clientPhoto = serializers.SerializerMethodField()
    clientTelephone = serializers.SerializerMethodField()
    restaurantNom = serializers.CharField(source="etablissement.nom", read_only=True)
    restaurantAdresse = serializers.CharField(source="etablissement.adresse", read_only=True)
    coursierNom = serializers.SerializerMethodField()
    coursierPhoto = serializers.SerializerMethodField()
    coursierTelephone = serializers.SerializerMethodField()
    estCoursierAssigne = serializers.SerializerMethodField()
    totalMontant = serializers.SerializerMethodField()
    totalValeurNumerique = serializers.IntegerField(source="total_fcfa", read_only=True)
    statut = serializers.SerializerMethodField()
    libelleStatut = serializers.SerializerMethodField()
    classeStatut = serializers.SerializerMethodField()
    dateAffichage = serializers.SerializerMethodField()
    adresseLivraison = serializers.CharField(source="adresse_livraison", read_only=True)
    articles = serializers.SerializerMethodField()
    methodePaiement = serializers.CharField(source="mode_paiement", read_only=True)

    def get_identifiantCommande(self, obj):
        return f"#{obj.reference}"

    def get_clientNom(self, obj):
        return obj.client.nom_complet if obj.client else "Client AYYOU"

    def get_clientPhoto(self, obj):
        if obj.client and obj.client.photo:
            return obj.client.photo.url
        return "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150"

    def get_clientTelephone(self, obj):
        return obj.client.telephone if obj.client else "+221 --"

    def get_coursierNom(self, obj):
        if hasattr(obj, "livraison") and obj.livraison and obj.livraison.livreur:
            return obj.livraison.livreur.utilisateur.nom_complet
        return "Non assigné"

    def get_coursierPhoto(self, obj):
        if hasattr(obj, "livraison") and obj.livraison and obj.livraison.livreur and obj.livraison.livreur.utilisateur.photo:
            return obj.livraison.livreur.utilisateur.photo.url
        return "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150"

    def get_coursierTelephone(self, obj):
        if hasattr(obj, "livraison") and obj.livraison and obj.livraison.livreur:
            return obj.livraison.livreur.utilisateur.telephone
        return None

    def get_estCoursierAssigne(self, obj):
        return bool(hasattr(obj, "livraison") and obj.livraison and obj.livraison.livreur)

    def get_totalMontant(self, obj):
        return f"{obj.total_fcfa:,} FCFA".replace(",", " ")

    def get_statut(self, obj):
        st = obj.statut
        if st in ["EN_ATTENTE_PAIEMENT", "CREEE_EN_ATTENTE"]:
            return "EN_ATTENTE"
        if st in ["EN_PREPARATION", "PRETE_POUR_RETRAIT", "COURSE_ASSIGNEE", "EN_VERIFICATION", "EN_LIVRAISON", "ARRIVE_CLIENT"]:
            return "EN_COURS"
        if st == "LIVREE":
            return "LIVREE"
        return "ANNULEE"

    def get_libelleStatut(self, obj):
        st = self.get_statut(obj)
        labels = {
            "EN_ATTENTE": "En attente",
            "EN_COURS": "En livraison",
            "LIVREE": "Livrée",
            "ANNULEE": "Annulée",
        }
        return labels.get(st, st)

    def get_classeStatut(self, obj):
        st = self.get_statut(obj)
        classes = {
            "EN_ATTENTE": "bg-amber-50 text-amber-700 border-amber-200",
            "EN_COURS": "bg-sky-50 text-sky-700 border-sky-200",
            "LIVREE": "bg-emerald-50 text-emerald-700 border-emerald-200",
            "ANNULEE": "bg-rose-50 text-rose-700 border-rose-200",
        }
        return classes.get(st, "bg-slate-50 text-slate-700")

    def get_dateAffichage(self, obj):
        if obj.date_creation:
            return obj.date_creation.strftime("%d %b. %Y à %H:%M")
        return "Date inconnue"

    def get_articles(self, obj):
        articles = []
        for ligne in obj.lignes.all():
            articles.append({
                "nom": ligne.nom_plat,
                "quantite": ligne.quantite,
                "prixUnitaire": ligne.prix_unitaire_fcfa,
            })
        return articles


class SerializerUtilisateurAdministration(serializers.Serializer):
    """Présentation des comptes utilisateurs pour la gestion Superadmin."""

    id = serializers.IntegerField()
    identifiant = serializers.SerializerMethodField()
    nom = serializers.CharField(source="nom_complet", read_only=True)
    email = serializers.EmailField(source="courriel", read_only=True)
    telephone = serializers.CharField(read_only=True)
    role = serializers.SerializerMethodField()
    badgeType = serializers.SerializerMethodField()
    iconeRole = serializers.SerializerMethodField()
    couleurIconeRole = serializers.SerializerMethodField()
    dateInscription = serializers.SerializerMethodField()
    statut = serializers.SerializerMethodField()
    photoUrl = serializers.SerializerMethodField()
    nombreCommandes = serializers.SerializerMethodField()

    def get_identifiant(self, obj):
        return f"usr-{obj.id}"

    def get_role(self, obj):
        mapping = {
            "CLIENT": "Utilisateur",
            "RESTAURANT": "Restaurant",
            "LIVREUR": "Livreur",
            "ADMINISTRATEUR": "Administrateur",
        }
        return mapping.get(obj.role, obj.role)

    def get_badgeType(self, obj):
        badges = {
            "CLIENT": "CLIENT STANDARD",
            "RESTAURANT": "PARTENAIRE PRO",
            "LIVREUR": "LIVREUR CERTIFIÉ",
            "ADMINISTRATEUR": "ADMIN SYSTÈME",
        }
        return badges.get(obj.role, "UTILISATEUR")

    def get_iconeRole(self, obj):
        icones = {
            "CLIENT": "fa-solid fa-user",
            "RESTAURANT": "fa-solid fa-utensils",
            "LIVREUR": "fa-solid fa-motorcycle",
            "ADMINISTRATEUR": "fa-solid fa-shield-halved",
        }
        return icones.get(obj.role, "fa-solid fa-user")

    def get_couleurIconeRole(self, obj):
        couleurs = {
            "CLIENT": "text-pink-500",
            "RESTAURANT": "text-amber-500",
            "LIVREUR": "text-purple-500",
            "ADMINISTRATEUR": "text-red-600",
        }
        return couleurs.get(obj.role, "text-slate-500")

    def get_dateInscription(self, obj):
        if obj.date_creation:
            return obj.date_creation.strftime("%d %b. %Y")
        return "Récemment"

    def get_statut(self, obj):
        return "ACTIF" if obj.is_active else "INACTIF"

    def get_photoUrl(self, obj):
        if obj.photo:
            return obj.photo.url
        return None

    def get_nombreCommandes(self, obj):
        if hasattr(obj, "commandes_client"):
            return obj.commandes_client.count()
        return 0

