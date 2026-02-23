"""
Stock queries — read-only operations.

All methods are classmethod on Stock and use no locking.
"""

from datetime import date
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from stockman.models.hold import Hold
from stockman.models.position import Position
from stockman.models.quant import Quant
from stockman.shelflife import filter_valid_quants


class StockQueries:
    """Read-only stock query methods."""

    @classmethod
    def available(cls, product, target_date: date | None = None,
                  position: Position | None = None) -> Decimal:
        """
        Available quantity for sale/hold.

        available = valid_quantity - active_holds

        Args:
            product: Product object
            target_date: Desired date (None = today)
            position: Specific position (None = all)

        Returns:
            Decimal with available quantity
        """
        target = target_date or date.today()
        ct = ContentType.objects.get_for_model(product)
        quants = Quant.objects.filter(content_type=ct, object_id=product.pk)

        if position:
            quants = quants.filter(position=position)

        quants = filter_valid_quants(quants, product, target)

        total = quants.aggregate(
            t=Coalesce(Sum('_quantity'), Decimal('0'))
        )['t']

        held_qs = Hold.objects.filter(
            content_type=ct,
            object_id=product.pk,
            target_date=target,
        ).active()
        if position:
            held_qs = held_qs.filter(quant__position=position)
        held = held_qs.aggregate(
            t=Coalesce(Sum('quantity'), Decimal('0'))
        )['t']

        return total - held

    @classmethod
    def demand(cls, product, target_date: date) -> Decimal:
        """
        Pending demand (holds without linked stock).

        Returns:
            Sum of Hold.quantity where quant=None and target_date=date
        """
        ct = ContentType.objects.get_for_model(product)
        return Hold.objects.filter(
            content_type=ct,
            object_id=product.pk,
            target_date=target_date,
            quant__isnull=True,
        ).active().aggregate(
            t=Coalesce(Sum('quantity'), Decimal('0'))
        )['t']

    @classmethod
    def committed(cls, product, target_date: date | None = None) -> Decimal:
        """
        Total quantity committed (active holds) for product/date.

        Args:
            product: Product object
            target_date: Date to check (None = today)

        Returns:
            Sum of active hold quantities
        """
        target = target_date or date.today()
        ct = ContentType.objects.get_for_model(product)

        return Hold.objects.filter(
            content_type=ct,
            object_id=product.pk,
            target_date=target,
        ).active().aggregate(
            t=Coalesce(Sum('quantity'), Decimal('0'))
        )['t']

    @classmethod
    def get_quant(cls, product, position: Position | None = None,
                  target_date: date | None = None, batch: str = '') -> Quant | None:
        """Get specific quant by coordinates."""
        ct = ContentType.objects.get_for_model(product)
        return Quant.objects.filter(
            content_type=ct,
            object_id=product.pk,
            position=position,
            target_date=target_date,
            batch=batch
        ).first()

    @classmethod
    def list_quants(cls, product=None, position: Position | None = None,
                    include_future: bool = True, include_empty: bool = False):
        """List quants with filters."""
        qs = Quant.objects.all()

        if product is not None:
            ct = ContentType.objects.get_for_model(product)
            qs = qs.filter(content_type=ct, object_id=product.pk)

        if position is not None:
            qs = qs.filter(position=position)

        if not include_future:
            qs = qs.filter(Q(target_date__isnull=True) | Q(target_date__lte=date.today()))

        if not include_empty:
            qs = qs.filter(_quantity__gt=0)

        return qs
