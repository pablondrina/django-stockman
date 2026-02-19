"""Django app configuration for Stockman."""

from django.apps import AppConfig


class StockmanConfig(AppConfig):
    """Configuration for Stockman app."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stockman'
    verbose_name = 'Gestão de Estoque'







