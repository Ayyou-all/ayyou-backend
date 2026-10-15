from django.urls import path

from . import views

urlpatterns = [
    path("moi/", views.VueMonProfil.as_view(), name="mon-profil"),
    path("moi/documents/", views.VueMesDocuments.as_view(), name="mes-documents"),
    path("changer-mot-de-passe/", views.VueChangerMotDePasse.as_view(), name="changer-mot-de-passe"),
    path("moi/mot-de-passe/", views.VueChangerMotDePasse.as_view(), name="mon-mot-de-passe"),
]

