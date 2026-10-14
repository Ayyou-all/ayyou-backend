from django.urls import path

from . import views

urlpatterns = [
    path("initier/", views.VueInitierPaiement.as_view(), name="initier-paiement"),
    path("webhook-ipn/", views.VueWebhookIpnPayTech.as_view(), name="webhook-ipn-paytech"),
    path("<str:reference>/statut/", views.VueStatutPaiement.as_view(), name="statut-paiement"),
]
