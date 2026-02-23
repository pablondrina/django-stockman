"""
Stock planning — production planning operations (plan, replan, realize).

Extension that builds on top of movements for production scheduling.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from stockman.exceptions import StockError
from stockman.models.enums import HoldStatus
from stockman.models.move import Move
from stockman.models.quant import Quant

logger = logging.getLogger('stockman')


class StockPlanning:
    """Production planning methods."""

    @classmethod
    def plan(cls, quantity, product, target_date,
             position=None, reference=None, user=None,
             reason='Produção planejada', **metadata):
        """
        Plan future production.

        Shortcut for receive() with mandatory target_date.
        """
        from stockman.services.movements import StockMovements
        return StockMovements.receive(
            quantity=quantity,
            product=product,
            position=position,
            target_date=target_date,
            reference=reference,
            user=user,
            reason=reason,
            **metadata
        )

    @classmethod
    def replan(cls, quantity, product, target_date,
               reason, user=None):
        """
        Adjust existing plan.

        Finds Quant(product, target_date) and adjusts quantity.

        Raises:
            StockError('QUANT_NOT_FOUND'): If no plan exists for the date
        """
        from stockman.services.movements import StockMovements
        from stockman.services.queries import StockQueries

        quant = StockQueries.get_quant(product, target_date=target_date)

        if quant is None:
            raise StockError('QUANT_NOT_FOUND', product=str(product), target_date=target_date)

        StockMovements.adjust(quant, quantity, reason, user)
        quant.refresh_from_db()
        return quant

    @classmethod
    def realize(cls, product, target_date, actual_quantity,
                to_position, user=None,
                reason='Produção realizada'):
        """
        Realize production (planned -> physical).

        1. Finds planned Quant
        2. Adjusts quantity if actual_quantity differs
        3. Transfers to physical position (target_date=None)
        4. Holds are transferred automatically

        Raises:
            StockError('QUANT_NOT_FOUND'): If no plan exists for the date
        """
        from stockman.services.queries import StockQueries

        quant = StockQueries.get_quant(product, target_date=target_date)

        if quant is None:
            raise StockError('QUANT_NOT_FOUND', product=str(product), target_date=target_date)

        ct = ContentType.objects.get_for_model(product)

        with transaction.atomic():
            locked_quant = Quant.objects.select_for_update().get(pk=quant.pk)

            # Adjust if different
            if locked_quant._quantity != actual_quantity:
                delta = actual_quantity - locked_quant._quantity
                Move.objects.create(
                    quant=locked_quant,
                    delta=delta,
                    reason=f"Ajuste produção: {reason}",
                    user=user
                )

            # Get or create physical quant
            physical_quant, _ = Quant.objects.get_or_create(
                content_type=ct,
                object_id=product.pk,
                position=to_position,
                target_date=None,
                batch='',
                defaults={'metadata': {}}
            )

            # Transfer: exit from planned, enter physical
            Move.objects.create(
                quant=locked_quant,
                delta=-actual_quantity,
                reason=f"Transferência: {reason}",
                user=user
            )

            Move.objects.create(
                quant=physical_quant,
                delta=actual_quantity,
                reason=f"Recebido de produção: {reason}",
                user=user
            )

            # Transfer holds
            locked_quant.holds.filter(
                status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED]
            ).update(quant=physical_quant)

            physical_quant.refresh_from_db()
            logger.info(
                "stock.realize",
                extra={
                    "product": str(product),
                    "target": str(target_date),
                    "actual_qty": str(actual_quantity),
                    "to_position": str(to_position),
                },
            )
            return physical_quant
