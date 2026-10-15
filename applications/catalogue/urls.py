from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

routeur = SimpleRouter()
routeur.register("catalogue/mes-plats", views.EnsembleVuesMesPlats, basename="mes-plats")

urlpatterns = [
    path("categories/", views.VueListeCategories.as_view(), name="liste-categories"),
    path("plats/", views.VueListePlats.as_view(), name="liste-plats"),
    path("plats/<int:pk>/", views.VueDetailPlat.as_view(), name="detail-plat"),
] + routeur.urls
