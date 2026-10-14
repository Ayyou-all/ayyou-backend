from django.urls import path

from . import views

urlpatterns = [
    path("<int:etablissement_id>/basculer/", views.VueBasculerAbonnement.as_view(), name="basculer-abonnement"),
    path("<int:etablissement_id>/aimer/", views.VueBasculerLikeEtablissement.as_view(), name="basculer-like-etablissement"),
    path("mes-abonnements/", views.VueMesAbonnements.as_view(), name="mes-abonnements"),
]
