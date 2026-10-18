from django.urls import path

from . import views

urlpatterns = [
    path("initier/", views.VueInitierPaiement.as_view(), name="initier-paiement"),
    path("verifier/", views.VueVerifierPaiement.as_view(), name="verifier-paiement"),
    path("webhook-ipn/", views.VueWebhookIpnPayTech.as_view(), name="webhook-ipn-paytech"),
    path("abonnement/", views.VueMonAbonnement.as_view(), name="mon-abonnement"),
    path("abonnement/payer/", views.VuePayerAbonnement.as_view(), name="payer-abonnement"),
    path("abonnement/verifier/", views.VueVerifierAbonnement.as_view(), name="verifier-abonnement"),
    path("<str:reference>/statut/", views.VueStatutPaiement.as_view(), name="statut-paiement"),
]
