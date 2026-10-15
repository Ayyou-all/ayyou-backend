from django.urls import path

from . import views

urlpatterns = [
    path("", views.VuePanier.as_view(), name="panier"),
    path("lignes/", views.VueLignesPanier.as_view(), name="lignes-panier"),
    path("lignes/<int:pk>/", views.VueLignePanier.as_view(), name="ligne-panier"),
]
