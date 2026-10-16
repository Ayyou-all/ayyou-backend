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


def _coordonnees(latitude, longitude):
    """Renvoie (lat, lng) en float, ou (None, None) si la position n'est pas connue."""
    if latitude is None or longitude is None:
        return None, None
    return float(latitude), float(longitude)


def _distance_restaurant_client_km(commande):
    """Distance à vol d'oiseau restaurant → client, ou None si une position manque."""
    from .tarification import calculer_distance_orthodromique_km

    lat_resto, lng_resto = _coordonnees(commande.etablissement.latitude, commande.etablissement.longitude)
    lat_client, lng_client = _coordonnees(commande.latitude_livraison, commande.longitude_livraison)
    if None in (lat_resto, lat_client):
        return None
    return round(calculer_distance_orthodromique_km(lat_resto, lng_resto, lat_client, lng_client), 1)


class SerializerPropositionLivraison(serializers.Serializer):
    """
    Course proposée à un livreur AVANT acceptation.

    Sécurité : aucune donnée personnelle du client (nom, téléphone, adresse, position exacte)
    n'est envoyée tant que le livreur n'a pas accepté la course.
    Les champs existent en camelCase et snake_case car l'écran Angular lit les deux.
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
    restaurantLatitude = serializers.SerializerMethodField()
    restaurant_latitude = serializers.SerializerMethodField()
    restaurantLongitude = serializers.SerializerMethodField()
    restaurant_longitude = serializers.SerializerMethodField()
    distanceKm = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    gainFcfa = serializers.SerializerMethodField()
    gain_livreur_fcfa = serializers.SerializerMethodField()
    articles = serializers.SerializerMethodField()

    def get_restaurantLatitude(self, commande):
        return _coordonnees(commande.etablissement.latitude, commande.etablissement.longitude)[0]

    def get_restaurant_latitude(self, commande):
        return self.get_restaurantLatitude(commande)

    def get_restaurantLongitude(self, commande):
        return _coordonnees(commande.etablissement.latitude, commande.etablissement.longitude)[1]

    def get_restaurant_longitude(self, commande):
        return self.get_restaurantLongitude(commande)

    def get_distanceKm(self, commande):
        return _distance_restaurant_client_km(commande)

    def get_distance_km(self, commande):
        return self.get_distanceKm(commande)

    def get_gainFcfa(self, commande):
        from .tarification import calculer_gain_livreur

        return calculer_gain_livreur(commande.frais_livraison_fcfa)

    def get_gain_livreur_fcfa(self, commande):
        return self.get_gainFcfa(commande)

    def get_articles(self, commande):
        return SerializerArticleVerification(commande.lignes.all(), many=True).data


class SerializerLivraisonEnCours(serializers.ModelSerializer):
    """Course acceptée : le livreur assigné reçoit les coordonnées du client pour livrer."""

    commande_id = serializers.IntegerField(source="commande.id", read_only=True)
    commande_reference = serializers.CharField(source="commande.reference", read_only=True)
    statut_commande = serializers.CharField(source="commande.statut", read_only=True)
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
    distance_km = serializers.SerializerMethodField()
    articles = serializers.SerializerMethodField()

    class Meta:
        model = Livraison
        fields = [
            "id",
            "etape",
            "gain_livreur_fcfa",
            "essais_code_echoues",
            "commande_id",
            "commande_reference",
            "statut_commande",
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
            "distance_km",
            "articles",
            "date_assignation",
        ]

    def get_restaurant_latitude(self, livraison):
        etab = livraison.commande.etablissement
        return _coordonnees(etab.latitude, etab.longitude)[0]

    def get_restaurant_longitude(self, livraison):
        etab = livraison.commande.etablissement
        return _coordonnees(etab.latitude, etab.longitude)[1]

    def get_client_latitude(self, livraison):
        cmd = livraison.commande
        return _coordonnees(cmd.latitude_livraison, cmd.longitude_livraison)[0]

    def get_client_longitude(self, livraison):
        cmd = livraison.commande
        return _coordonnees(cmd.latitude_livraison, cmd.longitude_livraison)[1]

    def get_distance_km(self, livraison):
        return _distance_restaurant_client_km(livraison.commande)

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
    disponibilite = serializers.ChoiceField(
        choices=[DisponibiliteLivreur.EN_LIGNE, DisponibiliteLivreur.HORS_LIGNE]
    )


class SerializerValidationPinLivreur(serializers.Serializer):
    code_pin = serializers.RegexField(r"^\d{4}$", error_messages={"invalid": "Le PIN contient 4 chiffres."})
