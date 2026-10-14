"""
Serializers du domaine Commande pour AYYOU.

Fournit des représentations adaptées aux différents acteurs :
- Client : suivi en direct, code PIN de sécurité, coordonnées du livreur
- Gérant Restaurant : gestion Kanban, détail des articles, délais
- Livreur : adresses de retrait et livraison, pointage des articles
- Admin : audit complet
"""

from rest_framework import serializers

from applications.communs.outils import construire_url_absolue

from .models import Commande, HistoriqueStatutCommande, LigneCommande, ModePaiement, StatutCommande


class SerializerLigneCommande(serializers.ModelSerializer):
    total_ligne_fcfa = serializers.IntegerField(read_only=True)

    class Meta:
        model = LigneCommande
        fields = [
            "id",
            "plat_id",
            "nom_plat",
            "prix_unitaire_fcfa",
            "quantite",
            "instructions_speciales",
            "est_verifie_par_livreur",
            "total_ligne_fcfa",
        ]


class SerializerHistoriqueStatut(serializers.ModelSerializer):
    auteur_nom = serializers.SerializerMethodField()

    class Meta:
        model = HistoriqueStatutCommande
        fields = [
            "id",
            "ancien_statut",
            "nouveau_statut",
            "auteur_nom",
            "commentaire",
            "date_transition",
        ]

    def get_auteur_nom(self, obj):
        return obj.auteur.nom_complet if obj.auteur else "Système AYYOU"


class SerializerCommandeClient(serializers.ModelSerializer):
    """
    Format adapté au frontend Angular client (interface CommandeClient / Suivi).
    """

    identifiant = serializers.CharField(source="reference", read_only=True)
    nom_restaurant = serializers.CharField(source="etablissement.nom", read_only=True)
    adresse_image_restaurant = serializers.SerializerMethodField()
    date_heure_texte = serializers.SerializerMethodField()
    delai_ou_remarque = serializers.SerializerMethodField()
    montant_total_fcfa = serializers.IntegerField(source="total_fcfa", read_only=True)
    code_livraison = serializers.SerializerMethodField()
    articles = SerializerLigneCommande(source="lignes", many=True, read_only=True)
    livreur = serializers.SerializerMethodField()
    etape_suivi = serializers.SerializerMethodField()
    heure_arrivee_estimee = serializers.SerializerMethodField()

    class Meta:
        model = Commande
        fields = [
            "id",
            "identifiant",
            "nom_restaurant",
            "adresse_image_restaurant",
            "date_heure_texte",
            "statut",
            "delai_ou_remarque",
            "montant_total_fcfa",
            "code_livraison",
            "livreur",
            "etape_suivi",
            "heure_arrivee_estimee",
            "articles",
            "est_en_cours",
            "adresse_livraison",
            "mode_paiement",
            "source_video_id",
        ]

    def get_adresse_image_restaurant(self, obj):
        return construire_url_absolue(self.context.get("request"), obj.etablissement.logo)

    def get_date_heure_texte(self, obj):
        return obj.date_creation.strftime("%d/%m/%Y, %H:%M")

    def get_delai_ou_remarque(self, obj):
        if obj.motif_refus_ou_annulation:
            return obj.motif_refus_ou_annulation
        if obj.delai_preparation_estime_minutes:
            return f"{obj.delai_preparation_estime_minutes} min"
        return obj.etablissement.delai_livraison_texte

    def get_code_livraison(self, obj):
        """
        Renvoie la liste des 4 chiffres (ex: [4, 8, 2, 5]) conforme au composant SuiviCommande.
        """
        user = self.context.get("request").user if self.context.get("request") else None
        # Le code PIN n'est visible que par le client propriétaire de la commande et l'admin
        if user and (user.is_superuser or user.id == obj.client_id):
            return [int(chiffre) for chiffre in str(obj.code_livraison_pin).zfill(4)]
        return None

    def get_etape_suivi(self, obj):
        """Traduction vers les étapes attendues par la vue client Angular."""
        mapping = {
            StatutCommande.EN_ATTENTE_PAIEMENT: "ATTENTE_PAIEMENT",
            StatutCommande.CREEE_EN_ATTENTE: "ACCEPTEE",
            StatutCommande.EN_PREPARATION: "PREPARATION",
            StatutCommande.PRETE_POUR_RETRAIT: "PREPARATION",
            StatutCommande.COURSE_ASSIGNEE: "EN_ROUTE",
            StatutCommande.EN_VERIFICATION: "EN_ROUTE",
            StatutCommande.EN_LIVRAISON: "EN_ROUTE",
            StatutCommande.ARRIVE_CLIENT: "ARRIVE_CLIENT",
            StatutCommande.LIVREE: "LIVREE",
            StatutCommande.REFUSEE_ANNULEE: "ANNULEE",
            StatutCommande.ECHEC_LIVRAISON: "ECHEC",
        }
        return mapping.get(obj.statut, "ACCEPTEE")

    def get_heure_arrivee_estimee(self, obj):
        return obj.heure_depart_livraison.strftime("%H:%M") if obj.heure_depart_livraison else ""

    def get_livreur(self, obj):
        livraison = getattr(obj, "livraison", None)
        if not livraison or not livraison.livreur:
            return None
        profil = livraison.livreur
        u = profil.utilisateur
        req = self.context.get("request")
        return {
            "nom": u.nom_complet,
            "vehicule": profil.nom_vehicule or profil.get_type_vehicule_display(),
            "adressePhoto": construire_url_absolue(req, u.photo) or "",
            "numeroTelephone": u.telephone,
            "latitude": float(profil.latitude) if profil.latitude else 14.7167,
            "longitude": float(profil.longitude) if profil.longitude else -17.4677,
        }


class SerializerCommandeRestaurant(serializers.ModelSerializer):
    """Vue commande pour l'espace Gérant (Kanban / Cuisine)."""

    client_nom = serializers.CharField(source="client.nom_complet", read_only=True)
    client_telephone = serializers.CharField(source="telephone_contact", read_only=True)
    articles = SerializerLigneCommande(source="lignes", many=True, read_only=True)

    livreur = serializers.SerializerMethodField()

    class Meta:
        model = Commande
        fields = [
            "id",
            "reference",
            "statut",
            "client_nom",
            "client_telephone",
            "adresse_livraison",
            "instructions_livraison",
            "sous_total_fcfa",
            "frais_livraison_fcfa",
            "total_fcfa",
            "delai_preparation_estime_minutes",
            "motif_refus_ou_annulation",
            "date_creation",
            "articles",
            "livreur",
        ]

    def get_livreur(self, obj):
        livraison = getattr(obj, "livraison", None)
        if not livraison or not livraison.livreur:
            return None
        profil = livraison.livreur
        u = profil.utilisateur
        req = self.context.get("request")
        return {
            "nom": u.nom_complet,
            "vehicule": profil.nom_vehicule or profil.get_type_vehicule_display(),
            "adressePhoto": construire_url_absolue(req, u.photo) or "",
            "numeroTelephone": u.telephone,
        }


class SerializerLigneCreation(serializers.Serializer):
    plat_id = serializers.IntegerField()
    quantite = serializers.IntegerField(min_value=1, default=1)
    instructions_speciales = serializers.CharField(required=False, allow_blank=True, default="")


class SerializerCreationCommande(serializers.Serializer):
    """Payload envoyé par le client pour transformer son panier en commande."""

    etablissement_id = serializers.IntegerField()
    adresse_livraison = serializers.CharField(max_length=255)
    telephone_contact = serializers.CharField(max_length=30, required=False, allow_blank=True)
    instructions_livraison = serializers.CharField(required=False, allow_blank=True, default="")
    mode_paiement = serializers.ChoiceField(choices=ModePaiement.choices, default=ModePaiement.WAVE)
    latitude_livraison = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude_livraison = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    source_video_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    articles = SerializerLigneCreation(many=True, required=False)


class SerializerActionAcceptation(serializers.Serializer):
    delai_minutes = serializers.IntegerField(min_value=5, max_value=180, default=25)


class SerializerActionRefus(serializers.Serializer):
    motif = serializers.CharField(max_length=255)


class SerializerValidationPin(serializers.Serializer):
    code_pin = serializers.CharField(min_length=4, max_length=4)
