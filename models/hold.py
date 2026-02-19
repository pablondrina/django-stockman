"""
Hold model — Temporary quantity reservation.
"""

from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from stockman.models.enums import HoldStatus


class Hold(models.Model):
    """
    Quantity hold for a customer/order.
    
    LIFECYCLE:
    
    ┌─────────────────────────────────────────────────────────────┐
    │                                                             │
    │   ┌─────────┐    confirm()    ┌───────────┐    fulfill()   │
    │   │ PENDING │ ──────────────► │ CONFIRMED │ ──────────────►│
    │   └─────────┘                 └───────────┘                │
    │        │                            │                       │
    │        │ release()                  │ release()             │
    │        ▼                            ▼                       │
    │   ┌──────────────────────────────────┐      ┌───────────┐  │
    │   │           RELEASED               │      │ FULFILLED │  │
    │   └──────────────────────────────────┘      └───────────┘  │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘
    
    TWO OPERATION MODES:
    
    1. RESERVATION (quant filled):
       - Hold linked to existing Quant
       - Quantity is "locked" for this customer
       - Decrements Quant.available
    
    2. DEMAND (quant=None):
       - Customer wants, but no stock/production
       - Used for planning ("how many want for Friday?")
       - Auto-links when production is planned (via hook)
    """
    
    # Product (always filled, regardless of mode)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,
        related_name='+',
    )
    object_id = models.PositiveIntegerField()
    product = GenericForeignKey('content_type', 'object_id')
    
    # Link to stock (None = demand)
    quant = models.ForeignKey(
        'stockman.Quant',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='holds',
        verbose_name=_('Estoque Vinculado'),
        help_text=_('Vazio = demanda (cliente quer, mas não há estoque)'),
    )
    
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_('Quantidade'),
    )
    target_date = models.DateField(
        db_index=True,
        verbose_name=_('Data Desejada'),
    )
    
    status = models.CharField(
        max_length=20,
        choices=HoldStatus.choices,
        default=HoldStatus.PENDING,
        db_index=True,
        verbose_name=_('Status'),
    )
    
    # Purpose (basket_item, order_item, etc)
    purpose_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    purpose_id = models.PositiveIntegerField(null=True, blank=True)
    purpose = GenericForeignKey('purpose_type', 'purpose_id')
    
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_('Expira em'),
        help_text=_('Se não concluído até esta data, será liberado automaticamente'),
    )
    
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Resolvido em'),
        help_text=_('Data de fulfillment ou release'),
    )
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        verbose_name = _('Reserva')
        verbose_name_plural = _('Reservas')
        indexes = [
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['content_type', 'object_id', 'target_date']),
            models.Index(fields=['status', 'quant']),
        ]
    
    @property
    def is_demand(self) -> bool:
        """Is this a demand (no linked stock)?"""
        return self.quant is None
    
    @property
    def is_reservation(self) -> bool:
        """Is this a reservation (with linked stock)?"""
        return self.quant is not None
    
    @property
    def is_active(self) -> bool:
        """
        Is active (pending or confirmed AND not expired)?
        
        A hold is only truly active if:
        1. Status is PENDING or CONFIRMED
        2. AND either has no expiration OR expiration is in the future
        """
        if self.status not in [HoldStatus.PENDING, HoldStatus.CONFIRMED]:
            return False
        if self.expires_at is None:
            return True
        return timezone.now() <= self.expires_at
    
    @property
    def is_expired(self) -> bool:
        """Has expired?"""
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at
    
    @property
    def hold_id(self) -> str:
        """Return hold identifier in standard format."""
        return f"hold:{self.pk}"
    
    def __str__(self) -> str:
        mode = "📋" if self.is_demand else "🔒"
        status_emoji = {
            HoldStatus.PENDING: '⏳',
            HoldStatus.CONFIRMED: '✓',
            HoldStatus.FULFILLED: '✅',
            HoldStatus.RELEASED: '↩',
        }
        emoji = status_emoji.get(self.status, '?')
        return f"{mode}{emoji} {self.quantity}x {self.product} ({self.target_date})"

