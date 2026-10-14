from django.urls import path

from . import views

urlpatterns = [
    path("", views.VueMesNotifications.as_view(), name="mes-notifications"),
    path("non-lues/count/", views.VueCompterNotificationsNonLues.as_view(), name="compter-notifications-non-lues"),
    path("<int:pk>/lire/", views.VueMarquerNotificationLue.as_view(), name="marquer-notification-lue"),
    path("tout-lire/", views.VueToutMarquerLu.as_view(), name="tout-marquer-lu"),
]
