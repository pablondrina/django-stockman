"""
Pytest fixtures for Stockman tests.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from catalog.models import Category, Product
from stockman.models import Position, PositionKind


User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username='testuser',
        password='testpass123'
    )


@pytest.fixture
def category(db):
    """Create a test category."""
    return Category.objects.create(
        name='Pães',
        slug='paes',
        is_active=True
    )


@pytest.fixture
def product(db, category):
    """Create a test product (non-perishable)."""
    return Product.objects.create(
        name='Pão de Forma',
        slug='pao-de-forma',
        category=category,
        price=Decimal('10.00'),
        is_active=True,
        is_batch_produced=True,
        shelflife=None,  # Non-perishable
        availability_policy='planned_ok'
    )


@pytest.fixture
def perishable_product(db, category):
    """Create a perishable product (shelflife=0, same day only)."""
    return Product.objects.create(
        name='Croissant',
        slug='croissant',
        category=category,
        price=Decimal('8.00'),
        is_active=True,
        is_batch_produced=True,
        shelflife=0,  # Same day only
        availability_policy='planned_ok'
    )


@pytest.fixture
def demand_product(db, category):
    """Create a product that accepts demand."""
    return Product.objects.create(
        name='Bolo Especial',
        slug='bolo-especial',
        category=category,
        price=Decimal('50.00'),
        is_active=True,
        is_batch_produced=True,
        shelflife=3,  # 3 days
        availability_policy='demand_ok'
    )


@pytest.fixture
def vitrine(db):
    """Get or create vitrine position."""
    position, _ = Position.objects.get_or_create(
        code='vitrine',
        defaults={
            'name': 'Vitrine Principal',
            'kind': PositionKind.PHYSICAL,
            'is_saleable': True
        }
    )
    return position


@pytest.fixture
def producao(db):
    """Get or create production position."""
    position, _ = Position.objects.get_or_create(
        code='producao',
        defaults={
            'name': 'Área de Produção',
            'kind': PositionKind.PHYSICAL,  # Changed from PROCESS
            'is_saleable': False
        }
    )
    return position


@pytest.fixture
def today():
    """Return today's date."""
    return date.today()


@pytest.fixture
def tomorrow():
    """Return tomorrow's date."""
    return date.today() + timedelta(days=1)


@pytest.fixture
def friday():
    """Return next Friday's date."""
    today = date.today()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7
    return today + timedelta(days=days_until_friday)


