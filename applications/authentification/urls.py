from django.urls import path

from . import views

urlpatterns = [
    path("inscription/", views.VueInscription.as_view(), name="inscription"),
    path("connexion/", views.VueConnexion.as_view(), name="connexion"),
    path("rafraichir/", views.VueRafraichissement.as_view(), name="rafraichir"),
    path("deconnexion/", views.VueDeconnexion.as_view(), name="deconnexion"),
    path("envoyer-code/", views.VueEnvoyerCodeVerification.as_view(), name="envoyer-code"),
    path("verifier-code/", views.VueVerifierCodeVerification.as_view(), name="verifier-code"),
    path("mot-de-passe-oublie/", views.VueMotDePasseOublie.as_view(), name="mot-de-passe-oublie"),
    path("reinitialiser-mot-de-passe/", views.VueReinitialiserMotDePasse.as_view(), name="reinitialiser-mot-de-passe"),
]
