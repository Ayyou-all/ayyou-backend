from django.urls import path

from . import views

urlpatterns = [
    path("statistiques/", views.VueStatistiquesGlobales.as_view(), name="admin-statistiques"),
    path("etablissements/", views.VueEtablissementsModeration.as_view(), name="admin-liste-etablissements"),
    path("etablissements/<int:pk>/decision/", views.VueDecisionEtablissement.as_view(), name="admin-decision-etablissement"),
    path("livreurs/", views.VueLivreursModeration.as_view(), name="admin-liste-livreurs"),
    path("livreurs/<int:pk>/decision/", views.VueDecisionLivreur.as_view(), name="admin-decision-livreur"),
    path("commandes/", views.VueCommandesAdministration.as_view(), name="admin-liste-commandes"),
    path("commandes/<int:pk>/<str:action>/", views.VueActionCommandeAdministration.as_view(), name="admin-action-commande"),
    path("abonnements/", views.VueAbonnementsRestaurants.as_view(), name="admin-abonnements"),
    path("abonnements/statistiques/", views.VueStatistiquesAbonnements.as_view(), name="admin-abonnements-statistiques"),
    path("utilisateurs/", views.VueUtilisateursAdministration.as_view(), name="admin-liste-utilisateurs"),
    path("utilisateurs/<int:pk>/basculer-statut/", views.VueBasculerStatutUtilisateur.as_view(), name="admin-basculer-statut-utilisateur"),
    path("utilisateurs/<int:pk>/alerter/", views.VueAlerterUtilisateur.as_view(), name="admin-alerter-utilisateur"),
]
