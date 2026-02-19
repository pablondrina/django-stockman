"""
Enums for Stockman models.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class PositionKind(models.TextChoices):
    """
    Type of position in space.
    
    PHYSICAL: Place where product exists in the real world.
              Examples: Vitrine, Depósito, Forno, Área de Produção, Em Trânsito
              Test: "If I go there, will I find the product?" → Yes
    
    VIRTUAL:  Accounting concept, product doesn't physically exist.
              Examples: Perdas, Ajustes de Inventário, Consumo Interno
              Test: "If I go there, will I find the product?" → No (there's no "there")
    """
    PHYSICAL = 'physical', _('Físico')      # Produto existe em lugar real
    VIRTUAL = 'virtual', _('Virtual')       # Registro contábil, produto não existe


class HoldStatus(models.TextChoices):
    """Hold lifecycle status."""
    PENDING = 'pending', _('Pendente')       # Created, awaiting confirmation
    CONFIRMED = 'confirmed', _('Confirmado') # Checkout started
    FULFILLED = 'fulfilled', _('Concluído')  # Delivered, stock decremented
    RELEASED = 'released', _('Liberado')     # Cancelled or expired

