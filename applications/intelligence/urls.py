from django.urls import path

from . import views

urlpatterns = [
    path("recommandations/", views.VueRecommandationsIA.as_view(), name="ia-recommandations"),
    path("chatbot/", views.VueChatbotCulinaire.as_view(), name="ia-chatbot"),
    path("recherche-vocale/", views.VueRechercheVocale.as_view(), name="ia-recherche-vocale"),
    path("restaurant/previsions/", views.VuePrevisionsRestaurant.as_view(), name="ia-previsions-restaurant"),
    path("restaurant/rapport-hebdo/", views.VueRapportHebdomadaireRestaurant.as_view(), name="ia-rapport-hebdo-restaurant"),
]
