from django.urls import path

from . import views

urlpatterns = [
    path("propositions/", views.VuePropositionsCourses.as_view(), name="propositions-courses"),
    path("<str:commande_id>/accepter/", views.VueAccepterMission.as_view(), name="accepter-mission"),
    path("<str:commande_id>/refuser/", views.VueRefuserCourse.as_view(), name="refuser-course"),
    path("mission-en-cours/", views.VueMissionEnCours.as_view(), name="mission-en-cours"),
    path("mission-en-cours/annuler/", views.VueAnnulerCourse.as_view(), name="annuler-course"),
    path("mission-en-cours/echec/", views.VueEchecLivraison.as_view(), name="echec-livraison"),
    path("mission-en-cours/pointer-article/", views.VuePointerArticle.as_view(), name="pointer-article"),
    path("mission-en-cours/depart-client/", views.VueDepartVersClient.as_view(), name="depart-client"),
    path("mission-en-cours/arrivee-client/", views.VueArriveeClient.as_view(), name="arrivee-client"),
    path("mission-en-cours/valider-pin/", views.VueCloturerLivraisonPin.as_view(), name="cloturer-pin"),
    path("position-gps/", views.VuePositionGpsLivreur.as_view(), name="position-gps-livreur"),
    path("position/", views.VuePositionGpsLivreur.as_view(), name="position-livreur"),
    path("disponibilite/", views.VueDisponibiliteLivreur.as_view(), name="disponibilite-livreur"),
    path("profil/", views.VueMonProfilLivreur.as_view(), name="profil-livreur"),
]
