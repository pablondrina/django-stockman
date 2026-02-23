# Django Stockman

Inventory management for Django with position-based stock tracking.

## Installation

```bash
pip install django-stockman
```

```python
INSTALLED_APPS = [
    ...
    'stockman',
    'stockman.contrib.admin_unfold',  # optional, for Unfold admin
]
```

```bash
python manage.py migrate
```

## Core Concepts

### Position
Where stock exists (warehouse, store, production area, etc.).

```python
from stockman.models import Position, PositionKind

pos = Position.objects.create(
    code="LOJA-01",
    name="Loja Centro",
    kind=PositionKind.STORE,
    is_saleable=True,
)
```

### Quant
Quantity cache at a space-time coordinate (product + position + date).

Quants are **read-only views** - never modify directly. Use the stock service.

### Move
Immutable ledger of stock changes. Every add/remove creates a Move.

### Hold
Temporary reservation (for orders, production, etc.).

## Usage

```python
from stockman import stock
from offerman.models import Product
from stockman.models import Position
from datetime import date

product = Product.objects.get(sku="CROISSANT")
position = Position.objects.get(code="LOJA-01")

# Add stock (production entry)
stock.add(
    product=product,
    position=position,
    qty=100,
    target_date=date.today(),
    reason="Production batch #123",
)

# Check availability
available = stock.available(product, position, date.today())
print(f"Available: {available}")

# Reserve stock (for an order)
hold = stock.reserve(
    product=product,
    position=position,
    qty=10,
    target_date=date.today(),
    purpose="order",
    purpose_id=12345,
)
print(f"Hold ID: {hold.hold_id}")

# Release reservation
stock.release(hold.hold_id, reason="Order cancelled")

# Remove stock (sale)
stock.remove(
    product=product,
    position=position,
    qty=5,
    target_date=date.today(),
    reason="Sale #456",
)
```

## Stock Service API

### stock.add()
Add stock to a position.

```python
stock.add(
    product=product,
    position=position,
    qty=Decimal("10"),
    target_date=date.today(),
    reason="Production",
    user=request.user,  # optional
    metadata={"batch": "123"},  # optional
)
```

### stock.remove()
Remove stock from a position.

```python
stock.remove(
    product=product,
    position=position,
    qty=Decimal("5"),
    target_date=date.today(),
    reason="Sale",
)
```

### stock.reserve()
Create a hold (reservation).

```python
hold = stock.reserve(
    product=product,
    position=position,
    qty=Decimal("10"),
    target_date=date.today(),
    purpose="order",
    purpose_id=order.id,
    is_demand=False,  # True for demand holds (affects planning)
)
```

### stock.release()
Release a hold.

```python
stock.release(hold_id, reason="Order completed")
```

### stock.available()
Check available quantity (quantity - held).

```python
qty = stock.available(product, position, date.today())
```

### stock.quantity()
Check total quantity (ignoring holds).

```python
qty = stock.quantity(product, position, date.today())
```

## Integration with Omniman

Stockman provides a stock backend for Omniman:

```python
# settings.py
OMNIMAN_STOCK_BACKEND = "omniman.contrib.stock.StockBackend"
```

This enables automatic stock checking and reservation during order commit.

## Admin (Unfold)

For enhanced admin UI with Unfold:

```python
INSTALLED_APPS = [
    'unfold',
    ...
    'stockman',
    'stockman.contrib.admin_unfold',
]
```

## Shopman Suite

Stockman is part of the [Shopman suite](https://github.com/pablondrina). The admin UI uses shared utilities from [django-shopman-commons](https://github.com/pablondrina/django-shopman-commons):

- `BaseModelAdmin` — textarea-aware ModelAdmin for Unfold
- `unfold_badge`, `unfold_badge_numeric` — colored badge helpers
- `format_quantity` — decimal formatting

```python
from shopman_commons.contrib.admin_unfold.base import BaseModelAdmin
from shopman_commons.contrib.admin_unfold.badges import unfold_badge, unfold_badge_numeric
from shopman_commons.formatting import format_quantity
```

## Requirements

- Python 3.11+
- Django 5.0+

## License

MIT
