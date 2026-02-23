"""Django app configuration for Stockman."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class StockmanConfig(AppConfig):
    """Configuration for Stockman app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "stockman"
    verbose_name = _("Gestão de Estoque")







