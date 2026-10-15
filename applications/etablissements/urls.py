from django.urls import path

from . import views

urlpatterns = [
    path("", views.VueListeEtablissements.as_view(), name="liste-etablissements"),
    path("mon-etablissement/", views.VueMonEtablissement.as_view(), name="mon-etablissement"),
    path("<int:pk>/", views.VueDetailEtablissement.as_view(), name="detail-etablissement"),
]
