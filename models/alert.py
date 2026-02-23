"""
StockAlert model — configurable min stock trigger per SKU.

First-class inventory solutions (Cin7, Unleashed, Shopify WMS) all support
alerting when stock drops below a configurable threshold. This model enables that.

Usage:
    # Set alert threshold
    StockAlert.objects.create(
        content_type=ct, object_id=product.pk,
        position=vitrine, min_quantity=10,
    )

    # Check alerts (in a periodic task or after stock changes)
    from stockman.services.alerts import check_alerts
    triggered = check_alerts()
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class StockAlert(models.Model):
    """
    Configurable stock alert per product (optionally per position).

    When available quantity drops below min_quantity, the alert is
    considered triggered. Consumers can query triggered alerts via
    StockAlert.objects.triggered() or subscribe to the
    stock_alert_triggered signal.
    """

    # Product reference (generic — works with any product model)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_('Tipo de Produto'),
    )
    object_id = models.PositiveIntegerField(verbose_name=_('ID do Produto'))
    product = GenericForeignKey('content_type', 'object_id')

    # Optional position filter (None = all positions combined)
    position = models.ForeignKey(
        'stockman.Position',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='alerts',
        verbose_name=_('Posição'),
        help_text=_('Vazio = soma de todas as posições'),
    )

    # Threshold
    min_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name=_('Quantidade Mínima'),
        help_text=_('Alerta dispara quando disponível < este valor'),
    )

    # Configuration
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('Ativo'),
    )

    # Tracking
    last_triggered_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Último disparo'),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Criado em'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Atualizado em'))

    class Meta:
        verbose_name = _('Alerta de Estoque')
        verbose_name_plural = _('Alertas de Estoque')
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id', 'position'],
                name='unique_stock_alert_per_product_position',
            ),
        ]
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self) -> str:
        pos = f" @ {self.position.code}" if self.position else ""
        return f"Alert: {self.product}{pos} < {self.min_quantity}"
