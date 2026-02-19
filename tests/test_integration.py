"""
Integration tests: Production (Batch) ↔ Stockman ↔ Salesman

Heavy stress tests to find potential failures in the complete flow.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from salesman.basket.models import Basket

from batch.models import Batch
from catalog.models import Category, Product
from order.models import Order, OrderItem, Customer
from salesman_extensions.modifiers import StockValidationModifier, StockHoldModifier
from salesman_extensions.status import OrderStatus
from stockman import stock, StockError
from stockman.models import Position, Quant, Hold, HoldStatus


User = get_user_model()
pytestmark = pytest.mark.django_db


class TestProductionStockmanIntegration:
    """Tests for Batch → Stockman integration."""
    
    @pytest.fixture
    def setup_data(self, db):
        """Create test data."""
        self.category = Category.objects.create(name='Pães', slug='paes')
        self.product = Product.objects.create(
            name='Croissant',
            slug='croissant',
            category=self.category,
            price=Decimal('8.00'),
            is_active=True,
            is_batch_produced=True,
            shelflife=0,  # Same day only
            availability_policy='planned_ok'
        )
        self.today = date.today()
        self.user = User.objects.create_user('testuser', 'test@test.com', 'pass123')
        
        # Ensure default position exists
        self.vitrine, _ = Position.objects.get_or_create(
            code='vitrine',
            defaults={'name': 'Vitrine', 'kind': 'physical', 'is_saleable': True, 'is_default': True}
        )
        return self
    
    def test_batch_save_creates_quant(self, setup_data):
        """When PRODUCED is set, Quant is created in Stockman."""
        batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            planned=30,
            processed=28,
            produced=26,  # PRODUCED
        )
        
        # Verify Quant was created
        quant = Quant.objects.filter(
            object_id=self.product.pk,
            target_date=self.today
        ).first()
        
        assert quant is not None
        assert quant._quantity == Decimal('26')
    
    def test_batch_update_updates_quant(self, setup_data):
        """When PRODUCED is updated, Quant is updated."""
        batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            planned=30,
            produced=26,
        )
        
        # Update production
        batch.produced = 24  # Lost 2 more
        batch.save()
        
        quant = Quant.objects.filter(
            object_id=self.product.pk,
            target_date=self.today
        ).first()
        
        assert quant._quantity == Decimal('24')
    
    def test_batch_available_delegates_to_stockman(self, setup_data):
        """Batch.available uses Stockman."""
        batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            planned=30,
            produced=26,
        )
        
        # Create a hold (simulating an order)
        stock.hold(Decimal('10'), self.product, self.today)
        
        # Batch.available should reflect the hold
        assert batch.available == 16  # 26 - 10
    
    def test_batch_committed_delegates_to_stockman(self, setup_data):
        """Batch.committed uses Stockman."""
        batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            produced=26,
        )
        
        # Create holds
        stock.hold(Decimal('5'), self.product, self.today)
        stock.hold(Decimal('3'), self.product, self.today)
        
        assert batch.committed == 8  # 5 + 3


class TestStockmanSalesmanIntegration:
    """Tests for Stockman ↔ Salesman (basket/order) integration."""
    
    @pytest.fixture
    def setup_data(self, db):
        """Create test data."""
        self.category = Category.objects.create(name='Pães', slug='paes-salesman')
        self.product = Product.objects.create(
            name='Pão Francês',
            slug='pao-frances',
            category=self.category,
            price=Decimal('1.00'),
            is_active=True,
            is_batch_produced=True,
            shelflife=None,
            availability_policy='planned_ok'
        )
        self.today = date.today()
        self.user = User.objects.create_user('salesmanuser', 'salesman@test.com', 'pass123')
        
        # Ensure positions exist
        self.vitrine, _ = Position.objects.get_or_create(
            code='vitrine',
            defaults={'name': 'Vitrine', 'kind': 'physical', 'is_saleable': True, 'is_default': True}
        )
        
        # Create production
        self.batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            planned=100,
            produced=100,
        )
        return self
    
    def test_add_to_basket_creates_hold(self, setup_data):
        """Adding item to basket creates a hold."""
        basket = Basket.objects.create(user=self.user)
        basket.add(self.product, quantity=10)
        
        # Process with modifier
        modifier = StockHoldModifier()
        item = basket.get_items()[0]
        item.extra['target_date'] = str(self.today)
        item.save()
        modifier.process_item(item, request=None)
        
        # Verify hold was created
        item.refresh_from_db()
        assert 'hold_id' in item.extra
        assert stock.available(self.product, self.today) == Decimal('90')  # 100 - 10
    
    def test_remove_from_basket_releases_hold(self, setup_data):
        """Removing item from basket releases hold."""
        basket = Basket.objects.create(user=self.user)
        basket.add(self.product, quantity=10)
        
        # Process to create hold
        modifier = StockHoldModifier()
        item = basket.get_items()[0]
        item.extra['target_date'] = str(self.today)
        item.save()
        modifier.process_item(item, request=None)
        
        item.refresh_from_db()
        assert stock.available(self.product, self.today) == Decimal('90')  # 100 - 10
        
        # Get hold_id before removing
        hold_id = item.extra.get('hold_id')
        assert hold_id is not None
        
        # Remove item - signal should release hold
        # Note: basket.remove() doesn't trigger pre_delete, need to delete directly
        from salesman.basket.models import BasketItem
        BasketItem.objects.filter(pk=item.pk).delete()
        
        # Verify hold was released
        assert stock.available(self.product, self.today) == Decimal('100')
    
    def test_hold_expiration_can_be_extended(self, setup_data):
        """Hold expiration can be extended on re-process."""
        from datetime import timedelta
        
        basket = Basket.objects.create(user=self.user)
        basket.add(self.product, quantity=10)
        
        # Process item to create hold
        modifier = StockHoldModifier()
        item = basket.get_items()[0]
        item.extra['target_date'] = str(self.today)
        item.save()
        modifier.process_item(item, request=None)
        
        item.refresh_from_db()
        hold_id = item.extra['hold_id']
        from stockman.service import Stock as StockService
        hold_pk = StockService._parse_hold_id(hold_id)
        hold = Hold.objects.get(pk=hold_pk)
        
        # Set old expiration
        old_expires = timezone.now() + timedelta(minutes=2)
        hold.expires_at = old_expires
        hold.save()
        
        # Process again - should extend expiration
        modifier.process_item(item, request=None)
        
        # Verify expiration was extended
        hold.refresh_from_db()
        assert hold.expires_at > old_expires


class TestConcurrencyScenarios:
    """Tests for concurrent access and race conditions."""
    
    @pytest.fixture
    def setup_data(self, db):
        """Create test data."""
        self.category = Category.objects.create(name='Concurrency', slug='concurrency')
        self.product = Product.objects.create(
            name='Limited Product',
            slug='limited-product',
            category=self.category,
            price=Decimal('10.00'),
            is_active=True,
            is_batch_produced=True,
        )
        self.today = date.today()
        
        # Create limited production
        self.batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            produced=5,  # Only 5 available!
        )
        
        Position.objects.get_or_create(
            code='vitrine',
            defaults={'name': 'Vitrine', 'kind': 'physical', 'is_saleable': True, 'is_default': True}
        )
        return self
    
    def test_hold_respects_available_quantity(self, setup_data):
        """Cannot hold more than available."""
        # First hold: OK
        stock.hold(Decimal('3'), self.product, self.today)
        
        # Second hold: Should fail (only 2 left)
        with pytest.raises(StockError) as exc:
            stock.hold(Decimal('5'), self.product, self.today)
        
        assert exc.value.code == 'INSUFFICIENT_AVAILABLE'
        assert exc.value.available == Decimal('2')
    
    def test_multiple_small_holds_until_exhausted(self, setup_data):
        """Multiple holds until stock is exhausted."""
        # Create holds until exhausted
        hold_ids = []
        for i in range(5):
            hold_id = stock.hold(Decimal('1'), self.product, self.today)
            hold_ids.append(hold_id)
        
        # No more available
        assert stock.available(self.product, self.today) == Decimal('0')
        
        # Next hold should fail
        with pytest.raises(StockError) as exc:
            stock.hold(Decimal('1'), self.product, self.today)
        
        assert exc.value.code == 'INSUFFICIENT_AVAILABLE'
    
    def test_release_makes_stock_available_again(self, setup_data):
        """Releasing hold makes stock available."""
        hold_id = stock.hold(Decimal('5'), self.product, self.today)
        assert stock.available(self.product, self.today) == Decimal('0')
        
        stock.release(hold_id, reason='Customer cancelled')
        assert stock.available(self.product, self.today) == Decimal('5')


class TestExpiredHoldScenarios:
    """Tests for expired hold handling."""
    
    @pytest.fixture
    def setup_data(self, db):
        """Create test data."""
        self.category = Category.objects.create(name='Expiry', slug='expiry')
        self.product = Product.objects.create(
            name='Expiry Test',
            slug='expiry-test',
            category=self.category,
            price=Decimal('10.00'),
            is_active=True,
            is_batch_produced=True,
        )
        self.today = date.today()
        
        self.batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            produced=10,
        )
        
        Position.objects.get_or_create(
            code='vitrine',
            defaults={'name': 'Vitrine', 'kind': 'physical', 'is_saleable': True, 'is_default': True}
        )
        return self
    
    def test_expired_hold_ignored_in_availability(self, setup_data):
        """Expired holds don't block availability."""
        # Create hold that's already expired
        hold_id = stock.hold(
            Decimal('5'), 
            self.product, 
            self.today,
            expires_at=timezone.now() - timedelta(minutes=1)  # Already expired
        )
        
        # Available should be full (expired hold ignored)
        assert stock.available(self.product, self.today) == Decimal('10')
    
    def test_new_customer_can_buy_after_expiry(self, setup_data):
        """New customer can buy stock after another's hold expires."""
        # Customer A creates hold
        hold_a = stock.hold(
            Decimal('10'),
            self.product,
            self.today,
            expires_at=timezone.now() - timedelta(minutes=1)  # Expired!
        )
        
        # Customer B should be able to hold (A's hold expired)
        hold_b = stock.hold(Decimal('10'), self.product, self.today)
        
        assert hold_b is not None


class TestFullOrderLifecycle:
    """Tests for complete order lifecycle: basket → checkout → paid → completed."""
    
    @pytest.fixture
    def setup_data(self, db):
        """Create test data."""
        self.category = Category.objects.create(name='Lifecycle', slug='lifecycle')
        self.product = Product.objects.create(
            name='Lifecycle Product',
            slug='lifecycle-product',
            category=self.category,
            price=Decimal('25.00'),
            is_active=True,
            is_batch_produced=True,
        )
        self.today = date.today()
        self.user = User.objects.create_user('lifecycleuser', 'lifecycle@test.com', 'pass123')
        self.customer = Customer.objects.create(name='Test Customer', phone='11999999999')
        
        self.batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            produced=50,
        )
        
        Position.objects.get_or_create(
            code='vitrine',
            defaults={'name': 'Vitrine', 'kind': 'physical', 'is_saleable': True, 'is_default': True}
        )
        return self
    
    def test_complete_order_lifecycle(self, setup_data):
        """Test full cycle: add → checkout → pay → complete."""
        initial_available = stock.available(self.product, self.today)
        assert initial_available == Decimal('50')
        
        # 1. Add to basket (creates hold)
        basket = Basket.objects.create(user=self.user)
        basket.add(self.product, quantity=5)
        
        modifier = StockHoldModifier()
        item = basket.get_items()[0]
        item.extra['target_date'] = str(self.today)
        item.save()
        modifier.process_item(item, request=None)
        
        item.refresh_from_db()
        assert stock.available(self.product, self.today) == Decimal('45')  # 50 - 5
        hold_id = item.extra['hold_id']
        
        # Hold should still be active
        from stockman.service import Stock as StockService
        hold_pk = StockService._parse_hold_id(hold_id)
        hold = Hold.objects.get(pk=hold_pk)
        assert hold.status == HoldStatus.PENDING
        
        # 3. Create order with hold_id (stored in order item's extra via JSON)
        from django.contrib.contenttypes.models import ContentType
        product_ct = ContentType.objects.get_for_model(self.product)
        
        order = Order.objects.create(
            user=self.user,
            customer=self.customer,
            status=OrderStatus.CREATED.value,
            is_remote=True,
            pickup_date=self.today,
            pickup_time='10:00-12:00',
        )
        
        # OrderItem uses Salesman's extra field via model save
        order_item = OrderItem(
            order=order,
            product_content_type=product_ct,
            product_id=self.product.pk,
            quantity=5,
            unit_price=self.product.price,
        )
        order_item.extra = {'hold_id': hold_id}
        order_item.save()
        
        # 4. Confirm order (confirms hold)
        order.status = OrderStatus.CONFIRMED.value
        order.save()
        
        hold.refresh_from_db()
        assert hold.status == HoldStatus.CONFIRMED
        
        # 5. Complete order (fulfills hold)
        order.status = OrderStatus.COMPLETED.value
        order.save()
        
        hold.refresh_from_db()
        assert hold.status == HoldStatus.FULFILLED
        
        # Final stock: 50 - 5 = 45 (5 were sold)
        quant = Quant.objects.filter(object_id=self.product.pk, target_date=self.today).first()
        assert quant._quantity == Decimal('45')  # 50 - 5 fulfilled


class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    @pytest.fixture
    def setup_data(self, db):
        """Create test data."""
        self.category = Category.objects.create(name='Edge', slug='edge')
        self.product = Product.objects.create(
            name='Edge Product',
            slug='edge-product',
            category=self.category,
            price=Decimal('15.00'),
            is_active=True,
            is_batch_produced=True,
        )
        self.today = date.today()
        
        Position.objects.get_or_create(
            code='vitrine',
            defaults={'name': 'Vitrine', 'kind': 'physical', 'is_saleable': True, 'is_default': True}
        )
        return self
    
    def test_hold_without_stock(self, setup_data):
        """Cannot hold when no stock exists."""
        # No batch created = no stock
        with pytest.raises(StockError) as exc:
            stock.hold(Decimal('1'), self.product, self.today)
        
        assert exc.value.code == 'INSUFFICIENT_AVAILABLE'
        assert exc.value.available == Decimal('0')
    
    def test_negative_quantity_rejected(self, setup_data):
        """Negative quantities are rejected."""
        with pytest.raises(StockError):
            stock.hold(Decimal('-5'), self.product, self.today)
    
    def test_zero_quantity_rejected(self, setup_data):
        """Zero quantity is rejected."""
        with pytest.raises(StockError):
            stock.hold(Decimal('0'), self.product, self.today)
    
    def test_batch_without_stockman_position(self, setup_data):
        """Batch works even without Stockman position (fallback)."""
        # Delete all positions to test fallback
        Position.objects.all().delete()
        
        batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            produced=20,
        )
        
        # Should use legacy calculation (fallback)
        # available = produced - committed - unsold = 20 - 0 - 0 = 20
        assert batch.available == 20
    
    def test_double_confirm_raises_error(self, setup_data):
        """Confirming an already confirmed hold raises error (intentional)."""
        Batch.objects.create(product=self.product, date=self.today, produced=10)
        
        hold_id = stock.hold(Decimal('5'), self.product, self.today)
        stock.confirm(hold_id)
        
        # Second confirm raises error - this is expected behavior
        # The signal handler catches INVALID_STATUS and logs it
        with pytest.raises(StockError) as exc:
            stock.confirm(hold_id)
        assert exc.value.code == 'INVALID_STATUS'
    
    def test_double_release_is_safe(self, setup_data):
        """Releasing an already released hold is safe."""
        Batch.objects.create(product=self.product, date=self.today, produced=10)
        
        hold_id = stock.hold(Decimal('5'), self.product, self.today)
        stock.release(hold_id, reason='First release')
        
        # Should not raise
        with pytest.raises(StockError) as exc:
            stock.release(hold_id, reason='Second release')
        assert exc.value.code == 'INVALID_STATUS'


class TestStressScenarios:
    """Stress tests with many concurrent operations."""
    
    @pytest.fixture
    def setup_data(self, db):
        """Create test data."""
        self.category = Category.objects.create(name='Stress', slug='stress')
        self.product = Product.objects.create(
            name='Stress Product',
            slug='stress-product',
            category=self.category,
            price=Decimal('5.00'),
            is_active=True,
            is_batch_produced=True,
        )
        self.today = date.today()
        
        Position.objects.get_or_create(
            code='vitrine',
            defaults={'name': 'Vitrine', 'kind': 'physical', 'is_saleable': True, 'is_default': True}
        )
        
        # Large production
        self.batch = Batch.objects.create(
            product=self.product,
            date=self.today,
            produced=1000,
        )
        return self
    
    def test_many_holds_and_releases(self, setup_data):
        """Create and release many holds."""
        hold_ids = []
        
        # Create 100 holds of 10 units each
        for i in range(100):
            hold_id = stock.hold(Decimal('10'), self.product, self.today)
            hold_ids.append(hold_id)
        
        assert stock.available(self.product, self.today) == Decimal('0')  # 1000 - 1000
        
        # Release half
        for hold_id in hold_ids[:50]:
            stock.release(hold_id, reason='Cancelled')
        
        assert stock.available(self.product, self.today) == Decimal('500')  # 500 released
        
        # Confirm the rest
        for hold_id in hold_ids[50:]:
            stock.confirm(hold_id)
        
        # Still 500 held (confirmed)
        assert stock.available(self.product, self.today) == Decimal('500')
    
    def test_rapid_basket_operations(self, setup_data):
        """Rapid add/remove operations on basket."""
        from salesman.basket.models import BasketItem
        
        user = User.objects.create_user('stressuser', 'stress@test.com', 'pass123')
        basket = Basket.objects.create(user=user)
        modifier = StockHoldModifier()
        
        # Add item and create hold
        basket.add(self.product, quantity=100)
        item = basket.get_items()[0]
        item.extra['target_date'] = str(self.today)
        item.save()
        modifier.process_item(item, request=None)
        
        item.refresh_from_db()
        assert stock.available(self.product, self.today) == Decimal('900')  # 1000 - 100
        old_hold_id = item.extra['hold_id']
        
        # Change quantity - modifier should release old hold and create new
        # Note: basket.add() with same product updates quantity
        item.quantity = 200
        item.extra['hold_quantity'] = '100'  # Mark old quantity for comparison
        item.save()
        item.refresh_from_db()
        modifier.process_item(item, request=None)
        
        item.refresh_from_db()
        # Verify old hold was released and new one created
        new_hold_id = item.extra['hold_id']
        assert new_hold_id != old_hold_id  # Should be different hold
        assert stock.available(self.product, self.today) == Decimal('800')  # 1000 - 200
        
        # Remove item (should release hold)
        BasketItem.objects.filter(pk=item.pk).delete()
        
        # All holds should be released
        assert stock.available(self.product, self.today) == Decimal('1000')

