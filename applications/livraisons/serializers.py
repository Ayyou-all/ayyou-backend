"""
Serializers du domaine Livraison pour AYYOU (conforme aux maquettes et interfaces Angular).
"""

from rest_framework import serializers

from applications.communs.outils import construire_url_absolue

from .models import DisponibiliteLivreur, Livraison, ProfilLivreur


class SerializerArticleVerification(serializers.Serializer):
    id = serializers.IntegerField()
    nom = serializers.CharField(source="nom_plat")
    nom_plat = serializers.CharField()
    quantite = serializers.IntegerField()
    format = serializers.CharField(default="Standard")
    instructions = serializers.CharField(source="instructions_speciales", allow_blank=True, default="")
    instructions_speciales = serializers.CharField(allow_blank=True, default="")
    est_verifie = serializers.BooleanField(source="est_verifie_par_livreur")


class SerializerPropositionLivraison(serializers.Serializer):
    """
    Format exact de l'écran « Proposition de livraison » côté livreur.
    Fournit à la fois les conventions camelCase et snake_case pour une interopérabilité complète.
    """

    identifiantCommande = serializers.CharField(source="reference")
    reference = serializers.CharField()
    commandeId = serializers.IntegerField(source="id")
    commande_id = serializers.IntegerField(source="id")
    restaurantNom = serializers.CharField(source="etablissement.nom")
    restaurant_nom = serializers.CharField(source="etablissement.nom")
    restaurantAdresse = serializers.CharField(source="etablissement.adresse")
    restaurant_adresse = serializers.CharField(source="etablissement.adresse")
    restaurantTelephone = serializers.CharField(source="etablissement.telephone")
    restaurant_telephone = serializers.CharField(source="etablissement.telephone")
    comptoirRetrait = serializers.SerializerMethodField()
    clientNom = serializers.CharField(source="client.nom_complet")
    client_nom = serializers.CharField(source="client.nom_complet")
    clientTelephone = serializers.CharField(source="telephone_contact")
    client_telephone = serializers.CharField(source="telephone_contact")
    clientAdresse = serializers.CharField(source="adresse_livraison")
    client_adresse = serializers.CharField(source="adresse_livraison")
    clientInstructions = serializers.CharField(source="instructions_livraison")
    instructions_client = serializers.CharField(source="instructions_livraison")
    distanceKm = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    gainFcfa = serializers.SerializerMethodField()
    gain_livreur_fcfa = serializers.SerializerMethodField()
    tempsRestantSec = serializers.IntegerField(default=30)
    temps_restant_secondes = serializers.IntegerField(default=30)
    tempsTrajetMin = serializers.SerializerMethodField()
    temps_trajet_minutes = serializers.SerializerMethodField()
    restaurantLatitude = serializers.SerializerMethodField()
    restaurantLongitude = serializers.SerializerMethodField()
    clientLatitude = serializers.SerializerMethodField()
    clientLongitude = serializers.SerializerMethodField()
    restaurant_latitude = serializers.SerializerMethodField()
    restaurant_longitude = serializers.SerializerMethodField()
    client_latitude = serializers.SerializerMethodField()
    client_longitude = serializers.SerializerMethodField()
    articles = serializers.SerializerMethodField()

    def get_restaurantLatitude(self, commande):
        if commande.etablissement and commande.etablissement.latitude:
            return float(commande.etablissement.latitude)
        return 14.6710

    def get_restaurantLongitude(self, commande):
        if commande.etablissement and commande.etablissement.longitude:
            return float(commande.etablissement.longitude)
        return -17.4320

    def get_clientLatitude(self, commande):
        if commande.latitude_livraison:
            return float(commande.latitude_livraison)
        return 14.6850

    def get_clientLongitude(self, commande):
        if commande.longitude_livraison:
            return float(commande.longitude_livraison)
        return -17.4520

    def get_restaurant_latitude(self, commande):
        return self.get_restaurantLatitude(commande)

    def get_restaurant_longitude(self, commande):
        return self.get_restaurantLongitude(commande)

    def get_client_latitude(self, commande):
        return self.get_clientLatitude(commande)

    def get_client_longitude(self, commande):
        return self.get_clientLongitude(commande)

    def get_comptoirRetrait(self, commande):
        return f"Guichet AYYOU - {commande.etablissement.nom}"

    def _calculer_distance_reelle_km(self, commande):
        try:
            import math
            lat1 = float(self.get_restaurantLatitude(commande))
            lon1 = float(self.get_restaurantLongitude(commande))
            lat2 = float(self.get_clientLatitude(commande))
            lon2 = float(self.get_clientLongitude(commande))

            # Formule de Haversine
            r = 6371.0  # Rayon terrestre moyen en kilomètres
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = (
                math.sin(dlat / 2.0) ** 2
                + math.cos(math.radians(lat1))
                * math.cos(math.radians(lat2))
                * math.sin(dlon / 2.0) ** 2
            )
            c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
            distance = round(r * c, 1)
            return max(0.5, distance)
        except Exception:
            return 2.5

    def get_distanceKm(self, commande):
        return self._calculer_distance_reelle_km(commande)

    def get_distance_km(self, commande):
        return self._calculer_distance_reelle_km(commande)

    def get_gainFcfa(self, commande):
        frais = commande.frais_livraison_fcfa if commande.frais_livraison_fcfa else 1500
        return max(int(frais * 0.8), 1000)

    def get_gain_livreur_fcfa(self, commande):
        return self.get_gainFcfa(commande)

    def get_tempsTrajetMin(self, commande):
        distance = self._calculer_distance_reelle_km(commande)
        # Estimation de trajet moto à Dakar (~25 km/h de moyenne + 5 min récupération / remise)
        return max(5, round((distance / 25.0) * 60 + 5))

    def get_temps_trajet_minutes(self, commande):
        return self.get_tempsTrajetMin(commande)

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
    restaurant_latitude = serializers.SerializerMethodField()
    restaurant_longitude = serializers.SerializerMethodField()
    client_latitude = serializers.SerializerMethodField()
    client_longitude = serializers.SerializerMethodField()
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
            "restaurant_latitude",
            "restaurant_longitude",
            "client_latitude",
            "client_longitude",
            "articles",
            "date_assignation",
        ]

    def get_restaurant_latitude(self, livraison):
        if livraison.commande and livraison.commande.etablissement and livraison.commande.etablissement.latitude:
            return float(livraison.commande.etablissement.latitude)
        return 14.6710

    def get_restaurant_longitude(self, livraison):
        if livraison.commande and livraison.commande.etablissement and livraison.commande.etablissement.longitude:
            return float(livraison.commande.etablissement.longitude)
        return -17.4320

    def get_client_latitude(self, livraison):
        if livraison.commande and livraison.commande.latitude_livraison:
            return float(livraison.commande.latitude_livraison)
        return 14.6850

    def get_client_longitude(self, livraison):
        if livraison.commande and livraison.commande.longitude_livraison:
            return float(livraison.commande.longitude_livraison)
        return -17.4520

    def get_articles(self, livraison):
        return SerializerArticleVerification(livraison.commande.lignes.all(), many=True).data


class SerializerProfilLivreur(serializers.ModelSerializer):
    nom_complet = serializers.CharField(source="utilisateur.nom_complet", read_only=True)
    nomComplet = serializers.CharField(source="utilisateur.nom_complet", read_only=True)
    prenom = serializers.CharField(source="utilisateur.prenom", read_only=True)
    nom = serializers.CharField(source="utilisateur.nom", read_only=True)
    courriel = serializers.EmailField(source="utilisateur.courriel", read_only=True)
    telephone = serializers.CharField(source="utilisateur.telephone", read_only=True)
    adresse = serializers.CharField(source="utilisateur.adresse", read_only=True)
    adresse_photo = serializers.SerializerMethodField()
    adressePhoto = serializers.SerializerMethodField()
    typeVehicule = serializers.CharField(source="type_vehicule", read_only=True)
    nomVehicule = serializers.CharField(source="nom_vehicule", read_only=True)
    zonePrincipale = serializers.CharField(source="zone_principale", read_only=True)
    statutValidation = serializers.CharField(source="statut_validation", read_only=True)
    est_disponible = serializers.SerializerMethodField()
    estDisponible = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    gains_du_jour_fcfa = serializers.SerializerMethodField()
    nombre_livraisons_jour = serializers.SerializerMethodField()
    gains_semaine = serializers.SerializerMethodField()
    activite_hebdomadaire = serializers.SerializerMethodField()
    details_quotidiens = serializers.SerializerMethodField()

    class Meta:
        model = ProfilLivreur
        fields = [
            "id",
            "nom_complet",
            "nomComplet",
            "prenom",
            "nom",
            "courriel",
            "telephone",
            "adresse",
            "adresse_photo",
            "adressePhoto",
            "type_vehicule",
            "typeVehicule",
            "nom_vehicule",
            "nomVehicule",
            "immatriculation",
            "zone_principale",
            "zonePrincipale",
            "disponibilite",
            "est_disponible",
            "estDisponible",
            "statut_validation",
            "statutValidation",
            "documents",
            "gains_du_jour_fcfa",
            "nombre_livraisons_jour",
            "gains_semaine",
            "activite_hebdomadaire",
            "details_quotidiens",
            "latitude",
            "longitude",
        ]

    def get_adresse_photo(self, obj):
        return construire_url_absolue(self.context.get("request"), obj.utilisateur.photo)

    def get_adressePhoto(self, obj):
        return self.get_adresse_photo(obj)

    def get_est_disponible(self, obj):
        return obj.disponibilite == DisponibiliteLivreur.EN_LIGNE

    def get_estDisponible(self, obj):
        return self.get_est_disponible(obj)

    def get_documents(self, obj):
        from applications.utilisateurs.serializers import SerializerDocumentJustificatif
        return SerializerDocumentJustificatif(obj.utilisateur.documents.all(), many=True, context=self.context).data

    def get_gains_du_jour_fcfa(self, obj):
        from django.utils import timezone
        aujourdhui = timezone.now().date()
        livraisons = obj.livraisons.filter(etape="LIVREE", date_assignation__date=aujourdhui)
        return sum(l.gain_livreur_fcfa for l in livraisons)

    def get_nombre_livraisons_jour(self, obj):
        from django.utils import timezone
        aujourdhui = timezone.now().date()
        return obj.livraisons.filter(etape="LIVREE", date_assignation__date=aujourdhui).count()

    def get_gains_semaine(self, obj):
        from django.utils import timezone
        aujourdhui = timezone.now().date()
        debut_semaine = aujourdhui - timezone.timedelta(days=aujourdhui.weekday())
        livraisons = obj.livraisons.filter(etape="LIVREE", date_assignation__date__gte=debut_semaine)
        total = sum(l.gain_livreur_fcfa for l in livraisons)
        count = livraisons.count()
        return {
            "montantTotalFcfa": total,
            "pourcentageEvolution": 0,
            "livraisonsSemaine": count,
            "heuresEnLigne": f"{count * 25 // 60}h {count * 25 % 60}m" if count > 0 else "0h",
        }

    def get_activite_hebdomadaire(self, obj):
        from django.utils import timezone
        aujourdhui = timezone.now().date()
        debut_semaine = aujourdhui - timezone.timedelta(days=aujourdhui.weekday())
        jours = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        result = []
        montants_jours = []
        for i in range(7):
            d = debut_semaine + timezone.timedelta(days=i)
            tot = sum(l.gain_livreur_fcfa for l in obj.livraisons.filter(etape="LIVREE", date_assignation__date=d))
            montants_jours.append(tot)
        max_m = max(montants_jours) if max(montants_jours) > 0 else 10000
        for i in range(7):
            pct = max(int((montants_jours[i] / max_m) * 100), 5) if montants_jours[i] > 0 else 5
            result.append({
                "jour": jours[i],
                "montantFcfa": montants_jours[i],
                "hauteurPourcentage": pct,
            })
        return result

    def get_details_quotidiens(self, obj):
        from django.utils import timezone
        aujourdhui = timezone.now().date()
        hier = aujourdhui - timezone.timedelta(days=1)
        liv_auj = obj.livraisons.filter(etape="LIVREE", date_assignation__date=aujourdhui)
        liv_hier = obj.livraisons.filter(etape="LIVREE", date_assignation__date=hier)
        res = []
        res.append({
            "titreDate": "Aujourd'hui",
            "nombreLivraisons": liv_auj.count(),
            "montantFcfa": sum(l.gain_livreur_fcfa for l in liv_auj),
            "icone": "fa-regular fa-calendar-check",
            "couleurFond": "bg-emerald-100/70 text-emerald-600",
        })
        res.append({
            "titreDate": "Hier",
            "nombreLivraisons": liv_hier.count(),
            "montantFcfa": sum(l.gain_livreur_fcfa for l in liv_hier),
            "icone": "fa-solid fa-clock-rotate-left",
            "couleurFond": "bg-slate-100 text-slate-500",
        })
        return res


class SerializerMiseAJourPosition(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)


class SerializerPointageArticle(serializers.Serializer):
    ligne_id = serializers.IntegerField()
    est_verifie = serializers.BooleanField()


class SerializerChangementDisponibilite(serializers.Serializer):
    disponibilite = serializers.ChoiceField(choices=DisponibiliteLivreur.choices)
