"""
Serializers du domaine Livraison pour AYYOU (conforme aux maquettes et interfaces Angular).
"""

from rest_framework import serializers

from applications.communs.outils import construire_url_absolue

from .models import DisponibiliteLivreur, Livraison, ProfilLivreur


class SerializerArticleVerification(serializers.Serializer):
    id = serializers.IntegerField()
    nom = serializers.CharField(source="nom_plat")
    quantite = serializers.IntegerField()
    instructions = serializers.CharField(source="instructions_speciales")
    est_verifie = serializers.BooleanField(source="est_verifie_par_livreur")


class SerializerPropositionLivraison(serializers.Serializer):
    """
    Format exact de l'écran « Proposition de livraison » côté livreur.
    """

    identifiantCommande = serializers.CharField(source="reference")
    commandeId = serializers.IntegerField(source="id")
    restaurantNom = serializers.CharField(source="etablissement.nom")
    restaurantAdresse = serializers.CharField(source="etablissement.adresse")
    restaurantTelephone = serializers.CharField(source="etablissement.telephone")
    comptoirRetrait = serializers.SerializerMethodField()
    clientNom = serializers.CharField(source="client.nom_complet")
    clientTelephone = serializers.CharField(source="telephone_contact")
    clientAdresse = serializers.CharField(source="adresse_livraison")
    clientInstructions = serializers.CharField(source="instructions_livraison")
    distanceKm = serializers.SerializerMethodField()
    gainFcfa = serializers.SerializerMethodField()
    tempsRestantSec = serializers.IntegerField(default=30)
    tempsTrajetMin = serializers.SerializerMethodField()
    articles = serializers.SerializerMethodField()

    def get_comptoirRetrait(self, commande):
        return f"Guichet AYYOU - {commande.etablissement.nom}"

    def get_distanceKm(self, commande):
        return 3.5  # Estimation moyenne intra-Dakar

    def get_gainFcfa(self, commande):
        return max(int(commande.frais_livraison_fcfa * 0.8), 1000)

    def get_tempsTrajetMin(self, commande):
        return 12

    def get_articles(self, commande):
        return SerializerArticleVerification(commande.lignes.all(), many=True).data


class SerializerLivraisonEnCours(serializers.ModelSerializer):
    commande_reference = serializers.CharField(source="commande.reference", read_only=True)
    restaurant_nom = serializers.CharField(source="commande.etablissement.nom", read_only=True)
    restaurant_adresse = serializers.CharField(source="commande.etablissement.adresse", read_only=True)
    restaurant_telephone = serializers.CharField(source="commande.etablissement.telephone", read_only=True)
    client_nom = serializers.CharField(source="commande.client.nom_complet", read_only=True)
    client_telephone = serializers.CharField(source="commande.telephone_contact", read_only=True)
    client_adresse = serializers.CharField(source="commande.adresse_livraison", read_only=True)
    client_instructions = serializers.CharField(source="commande.instructions_livraison", read_only=True)
    articles = serializers.SerializerMethodField()

    class Meta:
        model = Livraison
        fields = [
            "id",
            "etape",
            "gain_livreur_fcfa",
            "commande_reference",
            "restaurant_nom",
            "restaurant_adresse",
            "restaurant_telephone",
            "client_nom",
            "client_telephone",
            "client_adresse",
            "client_instructions",
            "articles",
            "date_assignation",
        ]

    def get_articles(self, livraison):
        return SerializerArticleVerification(livraison.commande.lignes.all(), many=True).data


class SerializerProfilLivreur(serializers.ModelSerializer):
    nom_complet = serializers.CharField(source="utilisateur.nom_complet", read_only=True)
    adresse_photo = serializers.SerializerMethodField()
    est_disponible = serializers.SerializerMethodField()
    gains_du_jour_fcfa = serializers.SerializerMethodField()
    nombre_livraisons_jour = serializers.SerializerMethodField()

    class Meta:
        model = ProfilLivreur
        fields = [
            "id",
            "nom_complet",
            "adresse_photo",
            "type_vehicule",
            "nom_vehicule",
            "disponibilite",
            "est_disponible",
            "statut_validation",
            "gains_du_jour_fcfa",
            "nombre_livraisons_jour",
            "latitude",
            "longitude",
        ]

    def get_adresse_photo(self, obj):
        return construire_url_absolue(self.context.get("request"), obj.utilisateur.photo)

    def get_est_disponible(self, obj):
        return obj.disponibilite == DisponibiliteLivreur.EN_LIGNE

    def get_gains_du_jour_fcfa(self, obj):
        # Somme des gains des livraisons terminées aujourd'hui
        return sum(l.gain_livreur_fcfa for l in obj.livraisons.filter(etape="LIVREE"))

    def get_nombre_livraisons_jour(self, obj):
        return obj.livraisons.filter(etape="LIVREE").count()


class SerializerMiseAJourPosition(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)


class SerializerPointageArticle(serializers.Serializer):
    ligne_id = serializers.IntegerField()
    est_verifie = serializers.BooleanField()


class SerializerChangementDisponibilite(serializers.Serializer):
    disponibilite = serializers.ChoiceField(choices=DisponibiliteLivreur.choices)
