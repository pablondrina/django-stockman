"""
Stock movements — state-changing operations (receive, issue, adjust).

All methods use transaction.atomic() with appropriate locking.
"""

import logging

from django.db import transaction

from stockman.exceptions import StockError
from stockman.models.move import Move
from stockman.models.quant import Quant

logger = logging.getLogger('stockman')

# Defaults when product doesn't implement StockableProduct protocol
PRODUCT_DEFAULTS = {
    'shelflife': None,
    'availability_policy': 'planned_ok',
}


class StockMovements:
    """State-changing stock movement methods."""

    @classmethod
    def receive(cls, quantity, product, position=None,
                target_date=None, batch='', reference=None,
                user=None, reason='Recebimento', **metadata):
        """
        Stock entry.

        Creates or updates Quant at specified coordinate.
        Creates Move with positive delta.

        Concurrency:
            - Runs under transaction.atomic()
            - Uses get_or_create with defaults
            - Move.save() updates _quantity atomically
        """
        if quantity <= 0:
            raise StockError('INVALID_QUANTITY', requested=quantity)

        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(product)

        with transaction.atomic():
            quant, created = Quant.objects.get_or_create(
                content_type=ct,
                object_id=product.pk,
                position=position,
                target_date=target_date,
                batch=batch,
                defaults={'metadata': metadata}
            )

            Move.objects.create(
                quant=quant,
                delta=quantity,
                reference=reference,
                reason=reason,
                user=user,
                metadata=metadata
            )

            quant.refresh_from_db()
            logger.info(
                "stock.receive",
                extra={
                    "product": str(product),
                    "qty": str(quantity),
                    "position": str(position),
                    "reason": reason,
                    "quant_id": quant.pk,
                },
            )
            return quant

    @classmethod
    def issue(cls, quantity, quant,
              reference=None, user=None, reason='Saída'):
        """
        Stock exit.

        Raises:
            StockError('INSUFFICIENT_QUANTITY'): If quantity > quant.available
            StockError('INVALID_QUANTITY'): If quantity <= 0

        Concurrency:
            - Runs under transaction.atomic()
            - Uses select_for_update() on Quant
            - Verifies availability after lock
        """
        if quantity <= 0:
            raise StockError('INVALID_QUANTITY', requested=quantity)

        with transaction.atomic():
            locked_quant = Quant.objects.select_for_update().get(pk=quant.pk)

            if locked_quant.available < quantity:
                raise StockError(
                    'INSUFFICIENT_QUANTITY',
                    available=locked_quant.available,
                    requested=quantity
                )

            move = Move.objects.create(
                quant=locked_quant,
                delta=-quantity,
                reference=reference,
                reason=reason,
                user=user
            )
            logger.info(
                "stock.issue",
                extra={
                    "quant_id": quant.pk,
                    "qty": str(quantity),
                    "reason": reason,
                },
            )
            return move

    @classmethod
    def adjust(cls, quant, new_quantity, reason, user=None):
        """
        Inventory adjustment.

        Calculates delta automatically: new_quantity - quant.quantity

        Raises:
            StockError('REASON_REQUIRED'): If reason is empty
        """
        if not reason:
            raise StockError('REASON_REQUIRED')

        with transaction.atomic():
            locked_quant = Quant.objects.select_for_update().get(pk=quant.pk)
            delta = new_quantity - locked_quant._quantity

            if delta == 0:
                return None

            move = Move.objects.create(
                quant=locked_quant,
                delta=delta,
                reason=f"Ajuste: {reason}",
                user=user
            )
            logger.info(
                "stock.adjust",
                extra={
                    "quant_id": quant.pk,
                    "delta": str(delta),
                    "reason": reason,
                },
            )
            return move
