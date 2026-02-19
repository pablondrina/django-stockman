"""
Stock Service — The single public interface for all stock operations.

Usage:
    from stockman import stock, StockError
    
    stock.plan(50, croissant, friday)
    hold_id = stock.hold(5, croissant, friday)
    stock.available(croissant, friday)  # 45
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from stockman.exceptions import StockError
from stockman.models.enums import HoldStatus
from stockman.models.hold import Hold
from stockman.models.move import Move
from stockman.models.position import Position
from stockman.models.quant import Quant


# Defaults when product doesn't implement StockableProduct protocol
PRODUCT_DEFAULTS = {
    'shelflife': None,
    'availability_policy': 'planned_ok',
}


class Stock:
    """
    Single interface for all stock operations.
    
    Parameter convention: (quantity, product, target_date, ...)
    Follows natural language: "Plan 50 croissants for Friday"
    
    IMPORTANT: All state-changing methods use atomic transactions
    with appropriate locking. See each method's docstring.
    """
    
    # ══════════════════════════════════════════════════════════════
    # CORE: QUERIES
    # ══════════════════════════════════════════════════════════════
    
    @classmethod
    def available(cls, product, target_date: date | None = None, position: Position | None = None) -> Decimal:
        """
        Available quantity for sale/hold.
        
        Considers:
        - Physical stock still valid (respecting shelflife)
        - Planned stock up to the date
        - Minus active holds (pending/confirmed)
        
        Args:
            product: Product object
            target_date: Desired date (None = today)
            position: Specific position (None = all)
        
        Returns:
            Decimal with available quantity
        
        Performance:
            O(1) for quantity read (uses _quantity cache)
            O(N) for active holds sum (N = holds, typically small)
        """
        target = target_date or date.today()
        shelflife = cls._get_product_attr(product, 'shelflife', None)
        
        ct = ContentType.objects.get_for_model(product)
        quants = Quant.objects.filter(content_type=ct, object_id=product.pk)
        
        if position:
            quants = quants.filter(position=position)
        
        if shelflife is not None:
            # Perishable product
            # Minimum production date to still be valid at target
            min_production = target - timedelta(days=shelflife)
            
            quants = quants.filter(
                # Physical created after min_production
                Q(
                    target_date__isnull=True,
                    created_at__date__gte=min_production
                ) |
                # Planned: produced between min_production and target
                Q(
                    target_date__gte=min_production,
                    target_date__lte=target
                )
            )
        else:
            # Non-perishable product
            quants = quants.filter(
                Q(target_date__isnull=True) |
                Q(target_date__lte=target)
            )
        
        # Sum _quantity (O(N) where N = filtered quants, typically small)
        total = quants.aggregate(
            t=Coalesce(Sum('_quantity'), Decimal('0'))
        )['t']
        
        # Subtract active holds for this date
        # IMPORTANT: Ignore expired holds even if status is still PENDING/CONFIRMED
        # This ensures availability is always correct, regardless of cron timing
        now = timezone.now()
        held = Hold.objects.filter(
            content_type=ct,
            object_id=product.pk,
            target_date=target,
            status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED]
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ).aggregate(
            t=Coalesce(Sum('quantity'), Decimal('0'))
        )['t']
        
        return total - held
    
    @classmethod
    def demand(cls, product, target_date: date) -> Decimal:
        """
        Pending demand (holds without linked stock).
        
        Useful for planning: "how many croissants do customers
        want for Friday but I don't have production yet?"
        
        Returns:
            Sum of Hold.quantity where quant=None and target_date=date
        """
        ct = ContentType.objects.get_for_model(product)
        now = timezone.now()
        return Hold.objects.filter(
            content_type=ct,
            object_id=product.pk,
            target_date=target_date,
            quant__isnull=True,
            status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED]
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ).aggregate(
            t=Coalesce(Sum('quantity'), Decimal('0'))
        )['t']
    
    @classmethod
    def committed(cls, product, target_date: date | None = None) -> Decimal:
        """
        Total quantity committed (active holds) for product/date.
        
        This is the sum of all PENDING and CONFIRMED holds that are
        not expired. Used by Production app to show how much is
        already reserved for a given date.
        
        Args:
            product: Product object
            target_date: Date to check (None = today)
        
        Returns:
            Sum of active hold quantities
        """
        target = target_date or date.today()
        ct = ContentType.objects.get_for_model(product)
        now = timezone.now()
        
        return Hold.objects.filter(
            content_type=ct,
            object_id=product.pk,
            target_date=target,
            status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED]
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=now)
        ).aggregate(
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
    
    # ══════════════════════════════════════════════════════════════
    # CORE: MOVEMENTS
    # ══════════════════════════════════════════════════════════════
    
    @classmethod
    def receive(cls, quantity: Decimal, product, position: Position | None = None,
                target_date: date | None = None, batch: str = '', reference=None,
                user=None, reason: str = 'Recebimento', **metadata) -> Quant:
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
            return quant
    
    @classmethod
    def issue(cls, quantity: Decimal, quant: Quant,
              reference=None, user=None, reason: str = 'Saída') -> Move:
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
            
            return Move.objects.create(
                quant=locked_quant,
                delta=-quantity,
                reference=reference,
                reason=reason,
                user=user
            )
    
    @classmethod
    def adjust(cls, quant: Quant, new_quantity: Decimal,
               reason: str, user=None) -> Move:
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
                # No change needed
                return None
            
            return Move.objects.create(
                quant=locked_quant,
                delta=delta,
                reason=f"Ajuste: {reason}",
                user=user
            )
    
    # ══════════════════════════════════════════════════════════════
    # CORE: HOLDS
    # ══════════════════════════════════════════════════════════════
    
    @classmethod
    def hold(cls, quantity: Decimal, product, target_date: date | None = None,
             purpose=None, expires_at=None, **metadata) -> str:
        """
        Create quantity hold.
        
        Behavior depends on product's availability_policy:
        - stock_only: Only creates if physical stock exists
        - planned_ok: Creates if physical OR planned stock exists
        - demand_ok: Always creates (as demand if no stock)
        
        Returns:
            hold_id in format "hold:{pk}"
        
        Raises:
            StockError('INSUFFICIENT_AVAILABLE'): If no availability
                and policy is not 'demand_ok'
        
        Concurrency:
            - Runs under transaction.atomic()
            - Uses select_for_update() on selected Quant
            - FIFO strategy by Quant.created_at
        """
        if quantity <= 0:
            raise StockError('INVALID_QUANTITY', requested=quantity)
        
        target = target_date or date.today()
        policy = cls._get_product_attr(product, 'availability_policy', 'planned_ok')
        ct = ContentType.objects.get_for_model(product)
        
        # Set purpose content type if provided
        purpose_type = None
        purpose_id = None
        if purpose is not None:
            purpose_type = ContentType.objects.get_for_model(purpose)
            purpose_id = purpose.pk
        
        with transaction.atomic():
            # Check availability
            available = cls.available(product, target)
            
            if available >= quantity:
                # Find a quant to link the hold to
                quant = cls._find_quant_for_hold(product, target, quantity)
                
                if quant:
                    # Lock quant and recheck
                    quant = Quant.objects.select_for_update().get(pk=quant.pk)
                    
                    if quant.available >= quantity:
                        hold = Hold.objects.create(
                            content_type=ct,
                            object_id=product.pk,
                            quant=quant,
                            quantity=quantity,
                            target_date=target,
                            status=HoldStatus.PENDING,
                            purpose_type=purpose_type,
                            purpose_id=purpose_id,
                            expires_at=expires_at,
                            metadata=metadata
                        )
                        return hold.hold_id
            
            # Not enough availability
            if policy == 'demand_ok':
                # Create demand hold (no quant)
                hold = Hold.objects.create(
                    content_type=ct,
                    object_id=product.pk,
                    quant=None,
                    quantity=quantity,
                    target_date=target,
                    status=HoldStatus.PENDING,
                    purpose_type=purpose_type,
                    purpose_id=purpose_id,
                    expires_at=expires_at,
                    metadata=metadata
                )
                return hold.hold_id
            
            raise StockError(
                'INSUFFICIENT_AVAILABLE',
                available=available,
                requested=quantity
            )
    
    @classmethod
    def confirm(cls, hold_id: str) -> Hold:
        """
        Confirm hold (checkout started).
        
        Transition: PENDING → CONFIRMED
        
        Raises:
            StockError('INVALID_HOLD'): If hold doesn't exist
            StockError('INVALID_STATUS'): If status is not PENDING
        """
        pk = cls._parse_hold_id(hold_id)
        
        with transaction.atomic():
            try:
                hold = Hold.objects.select_for_update().get(pk=pk)
            except Hold.DoesNotExist:
                raise StockError('INVALID_HOLD', hold_id=hold_id)
            
            if hold.status != HoldStatus.PENDING:
                raise StockError(
                    'INVALID_STATUS',
                    current=hold.status,
                    expected=HoldStatus.PENDING
                )
            
            hold.status = HoldStatus.CONFIRMED
            hold.save(update_fields=['status'])
            return hold
    
    @classmethod
    def release(cls, hold_id: str, reason: str = 'Liberado') -> Hold:
        """
        Release hold (cancellation).
        
        Transition: PENDING|CONFIRMED → RELEASED
        
        Raises:
            StockError('INVALID_HOLD'): If hold doesn't exist
            StockError('INVALID_STATUS'): If already fulfilled/released
        """
        pk = cls._parse_hold_id(hold_id)
        
        with transaction.atomic():
            try:
                hold = Hold.objects.select_for_update().get(pk=pk)
            except Hold.DoesNotExist:
                raise StockError('INVALID_HOLD', hold_id=hold_id)
            
            if hold.status not in [HoldStatus.PENDING, HoldStatus.CONFIRMED]:
                raise StockError(
                    'INVALID_STATUS',
                    current=hold.status,
                    expected=[HoldStatus.PENDING, HoldStatus.CONFIRMED]
                )
            
            hold.status = HoldStatus.RELEASED
            hold.resolved_at = timezone.now()
            hold.metadata['release_reason'] = reason
            hold.save(update_fields=['status', 'resolved_at', 'metadata'])
            return hold
    
    @classmethod
    def fulfill(cls, hold_id: str, reference=None, user=None) -> Move:
        """
        Fulfill hold (deliver to customer).
        
        1. Validates status is CONFIRMED
        2. Creates negative Move on linked Quant
        3. Transition: CONFIRMED → FULFILLED
        
        Returns:
            Created Move
        
        Raises:
            StockError('INVALID_HOLD'): If hold doesn't exist
            StockError('INVALID_STATUS'): If status is not CONFIRMED
            StockError('HOLD_IS_DEMAND'): If hold.quant is None
        """
        pk = cls._parse_hold_id(hold_id)
        
        with transaction.atomic():
            try:
                hold = Hold.objects.select_for_update().get(pk=pk)
            except Hold.DoesNotExist:
                raise StockError('INVALID_HOLD', hold_id=hold_id)
            
            if hold.status != HoldStatus.CONFIRMED:
                raise StockError(
                    'INVALID_STATUS',
                    current=hold.status,
                    expected=HoldStatus.CONFIRMED
                )
            
            if hold.quant is None:
                raise StockError('HOLD_IS_DEMAND', hold_id=hold_id)
            
            # Lock quant
            quant = Quant.objects.select_for_update().get(pk=hold.quant_id)
            
            # Create exit move
            move = Move.objects.create(
                quant=quant,
                delta=-hold.quantity,
                reference=reference,
                reason=f"Entrega hold:{hold.pk}",
                user=user
            )
            
            # Update hold status
            hold.status = HoldStatus.FULFILLED
            hold.resolved_at = timezone.now()
            hold.save(update_fields=['status', 'resolved_at'])
            
            return move
    
    @classmethod
    def release_expired(cls) -> int:
        """
        Release all expired holds.
        
        Searches: status IN (PENDING, CONFIRMED) AND expires_at < now
        Action: Changes status to RELEASED
        
        Returns:
            Number of holds released
        
        Usage:
            Call periodically via celery beat or cron.
            Recommended: every 5 minutes.
        
        Concurrency:
            - Runs under transaction.atomic()
            - Uses select_for_update() with SKIP LOCKED
            - Safe for multiple instances
        """
        now = timezone.now()
        count = 0
        
        with transaction.atomic():
            expired = Hold.objects.select_for_update(skip_locked=True).filter(
                status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED],
                expires_at__lt=now
            )
            
            for hold in expired:
                hold.status = HoldStatus.RELEASED
                hold.resolved_at = now
                hold.metadata['release_reason'] = 'Expirado automaticamente'
                hold.save(update_fields=['status', 'resolved_at', 'metadata'])
                count += 1
        
        return count
    
    # ══════════════════════════════════════════════════════════════
    # EXTENSION: PLANNING
    # ══════════════════════════════════════════════════════════════
    
    @classmethod
    def plan(cls, quantity: Decimal, product, target_date: date,
             position: Position | None = None, reference=None, user=None,
             reason: str = 'Produção planejada', **metadata) -> Quant:
        """
        Plan future production.
        
        Shortcut for receive() with mandatory target_date.
        """
        return cls.receive(
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
    def replan(cls, quantity: Decimal, product, target_date: date,
               reason: str, user=None) -> Quant:
        """
        Adjust existing plan.
        
        Finds Quant(product, target_date) and adjusts quantity.
        
        Raises:
            StockError('QUANT_NOT_FOUND'): If no plan exists for the date
        """
        quant = cls.get_quant(product, target_date=target_date)
        
        if quant is None:
            raise StockError('QUANT_NOT_FOUND', product=str(product), target_date=target_date)
        
        cls.adjust(quant, quantity, reason, user)
        quant.refresh_from_db()
        return quant
    
    @classmethod
    def realize(cls, product, target_date: date, actual_quantity: Decimal,
                to_position: Position, user=None,
                reason: str = 'Produção realizada') -> Quant:
        """
        Realize production (planned → physical).
        
        1. Finds planned Quant
        2. Adjusts quantity if actual_quantity differs
        3. Transfers to physical position (target_date=None)
        4. Holds are transferred automatically
        
        Raises:
            StockError('QUANT_NOT_FOUND'): If no plan exists for the date
        """
        quant = cls.get_quant(product, target_date=target_date)
        
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
            return physical_quant
    
    # ══════════════════════════════════════════════════════════════
    # INTERNALS
    # ══════════════════════════════════════════════════════════════
    
    @classmethod
    def _get_product_attr(cls, product, attr: str, default=None):
        """Get product attribute with fallback to default."""
        value = getattr(product, attr, None)
        if value is not None:
            return value
        return PRODUCT_DEFAULTS.get(attr, default)
    
    @classmethod
    def _parse_hold_id(cls, hold_id: str) -> int:
        """Extract PK from hold_id."""
        if hold_id and hold_id.startswith('hold:'):
            try:
                return int(hold_id.split(':')[1])
            except (IndexError, ValueError):
                pass
        raise StockError('INVALID_HOLD', hold_id=hold_id)
    
    @classmethod
    def _find_quant_for_hold(cls, product, target_date: date, quantity: Decimal) -> Quant | None:
        """Find a quant with enough availability for the hold (FIFO)."""
        ct = ContentType.objects.get_for_model(product)
        shelflife = cls._get_product_attr(product, 'shelflife', None)
        
        quants = Quant.objects.filter(
            content_type=ct,
            object_id=product.pk
        )
        
        if shelflife is not None:
            min_production = target_date - timedelta(days=shelflife)
            quants = quants.filter(
                Q(target_date__isnull=True, created_at__date__gte=min_production) |
                Q(target_date__gte=min_production, target_date__lte=target_date)
            )
        else:
            quants = quants.filter(
                Q(target_date__isnull=True) |
                Q(target_date__lte=target_date)
            )
        
        # Order by created_at (FIFO) and filter by available
        for quant in quants.order_by('created_at'):
            if quant.available >= quantity:
                return quant
        
        return None

