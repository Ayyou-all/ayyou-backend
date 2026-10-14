"""
Configuration Django Admin pour les notifications.
"""

from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class AdminNotification(admin.ModelAdmin):
    list_display = ["titre", "destinataire", "type_notification", "est_lue", "reference_commande", "date_creation"]
    list_filter = ["type_notification", "est_lue", "date_creation"]
    search_fields = ["titre", "message", "destinataire__email", "reference_commande"]
