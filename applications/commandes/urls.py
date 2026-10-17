from django.urls import path

from . import views

urlpatterns = [
    path("", views.VueCommandesClient.as_view(), name="commandes-client"),
    path("restaurant/", views.VueCommandesRestaurant.as_view(), name="commandes-restaurant"),
    path("restaurant/statistiques/", views.VueStatistiquesRestaurant.as_view(), name="statistiques-restaurant"),
    path("estimation/", views.VueEstimationCommande.as_view(), name="estimation-commande"),
    path("<str:pk>/", views.VueDetailCommandeClient.as_view(), name="detail-commande-client"),
    path("<str:pk>/annuler/", views.VueAnnulerCommandeClient.as_view(), name="annuler-commande-client"),
    path("<str:pk>/accepter/", views.VueAccepterCommande.as_view(), name="accepter-commande"),
    path("<str:pk>/refuser/", views.VueRefuserCommande.as_view(), name="refuser-commande"),
    path("<str:pk>/marquer-prete/", views.VueMarquerPreteCommande.as_view(), name="marquer-prete-commande"),
    path("<str:pk>/remettre-au-livreur/", views.VueRemettreAuLivreur.as_view(), name="remettre-au-livreur"),
    path("<str:pk>/valider-pin/", views.VueValiderPinLivraison.as_view(), name="valider-pin-commande"),
    path("<str:pk>/historique/", views.VueHistoriqueCommande.as_view(), name="historique-commande"),
]
