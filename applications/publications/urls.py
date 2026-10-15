from django.urls import path

from . import views

urlpatterns = [
    path("fil/", views.VueFilPublications.as_view(), name="fil-publications"),
    path("<int:pk>/", views.VueDetailPublication.as_view(), name="detail-publication"),
    path("<int:pk>/like/", views.VueToggleLikePublication.as_view(), name="like-publication"),
    path("<int:pk>/aimer/", views.VueToggleLikePublication.as_view(), name="aimer-publication"),
    path("<int:pk>/vue/", views.VueIncrementerVue.as_view(), name="vue-publication"),
    path("<int:pk>/partage/", views.VueIncrementerPartage.as_view(), name="partage-publication"),
    path("studio/", views.VueStudioPublications.as_view(), name="studio-publications"),
    path("studio/<int:pk>/", views.VueSupprimerPublicationStudio.as_view(), name="supprimer-publication-studio"),
]
