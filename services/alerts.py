"""
Stock alerts — check and trigger min stock alerts.

Usage:
    from stockman.services.alerts import check_alerts

    # Run periodically (celery beat, cron) or after stock changes
    triggered = check_alerts()
    # Returns list of (StockAlert, current_available) tuples
"""

import logging
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from stockman.models.alert import StockAlert
from stockman.models.hold import Hold
from stockman.models.quant import Quant

logger = logging.getLogger('stockman')


def check_alerts(product=None) -> list[tuple[StockAlert, Decimal]]:
    """
    Check all active alerts and return those that are triggered.

    An alert is triggered when available quantity < min_quantity.

    Args:
        product: Optional product to check alerts for (None = all).

    Returns:
        List of (alert, current_available) tuples for triggered alerts.
    """
    qs = StockAlert.objects.filter(is_active=True)
    if product is not None:
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(product)
        qs = qs.filter(content_type=ct, object_id=product.pk)

    triggered = []
    now = timezone.now()

    for alert in qs.select_related('position'):
        quant_qs = Quant.objects.filter(
            content_type_id=alert.content_type_id,
            object_id=alert.object_id,
        )
        if alert.position:
            quant_qs = quant_qs.filter(position=alert.position)

        # Physical stock only (no future planned)
        from django.db.models import Q
        quant_qs = quant_qs.filter(
            Q(target_date__isnull=True) | Q(target_date__lte=date.today())
        )

        total = quant_qs.aggregate(
            t=Coalesce(Sum('_quantity'), Decimal('0'))
        )['t']

        held_qs = Hold.objects.filter(
            content_type_id=alert.content_type_id,
            object_id=alert.object_id,
            target_date=date.today(),
        ).active()
        if alert.position:
            held_qs = held_qs.filter(quant__position=alert.position)
        held = held_qs.aggregate(
            t=Coalesce(Sum('quantity'), Decimal('0'))
        )['t']

        available = total - held

        if available < alert.min_quantity:
            alert.last_triggered_at = now
            alert.save(update_fields=['last_triggered_at'])
            triggered.append((alert, available))
            logger.warning(
                "stock.alert.triggered",
                extra={
                    "alert_id": alert.pk,
                    "product_id": alert.object_id,
                    "min_quantity": str(alert.min_quantity),
                    "available": str(available),
                    "position": str(alert.position) if alert.position else "all",
                },
            )

    return triggered
