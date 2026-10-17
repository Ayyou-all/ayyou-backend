"""Serializers du panier."""

from rest_framework import serializers

from applications.catalogue.serializers import SerializerPlat
from applications.communs.outils import construire_url_absolue

from .models import LignePanier


class SerializerLignePanier(serializers.ModelSerializer):
    plat = SerializerPlat(read_only=True)
    total_ligne_fcfa = serializers.SerializerMethodField()

    class Meta:
        model = LignePanier
        fields = ["id", "plat", "quantite", "instructions_speciales", "total_ligne_fcfa"]

    def get_total_ligne_fcfa(self, ligne):
        return ligne.plat.prix_fcfa * ligne.quantite


class SerializerAjoutPanier(serializers.Serializer):
    plat_id = serializers.IntegerField()
    quantite = serializers.IntegerField(min_value=1, max_value=50, default=1)
    instructions_speciales = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class SerializerModificationLignePanier(serializers.ModelSerializer):
    quantite = serializers.IntegerField(min_value=1, max_value=50, required=False)

    class Meta:
        model = LignePanier
        fields = ["quantite", "instructions_speciales"]


def serialiser_panier_groupe(panier: dict, requete) -> dict:
    """Transforme le résultat de `calculer_panier_groupe` en JSON (interface Angular `PanierClient`)."""
    contexte = {"request": requete}
    return {
        "paniers_par_etablissement": [
            {
                "identifiant_etablissement": groupe["etablissement"].id,
                "nom_etablissement": groupe["etablissement"].nom,
                "adresse_logo_etablissement": construire_url_absolue(requete, groupe["etablissement"].logo),
                "delai_livraison": groupe["etablissement"].delai_livraison_texte,
                "lignes": SerializerLignePanier(groupe["lignes"], many=True, context=contexte).data,
                "sous_total_fcfa": groupe["sous_total_fcfa"],
                "est_commandable": groupe["est_commandable"],
                "avertissements": groupe["avertissements"],
            }
            for groupe in panier["paniers_par_etablissement"]
        ],
        "nombre_total_articles": panier["nombre_total_articles"],
        "total_global_fcfa": panier["total_global_fcfa"],
    }
