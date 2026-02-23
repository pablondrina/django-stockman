# Availability Semantics

Formal definitions for how Stockman computes stock availability.

---

## Core Quantities

### on_hand

Total physical quantity of a product at a coordinate (position + target_date).

```
on_hand(product, position, target_date) = SUM(Quant._quantity)
    WHERE Quant.product = product
      AND Quant.position = position (or all positions if None)
      AND Quant is valid for target_date (see Shelflife Filtering below)
```

`Quant._quantity` is a **cache** maintained atomically by `Move.save()`. The true value is always `SUM(Move.delta)` for all Moves on that Quant. The cache can be audited and corrected via `Quant.recalculate()`.

### committed

Quantity reserved by active holds. A hold is "active" when:
1. Its status is PENDING or CONFIRMED, **and**
2. It has no expiration (`expires_at IS NULL`) **or** its expiration is in the future (`expires_at >= now`)

```
committed(product, target_date) = SUM(Hold.quantity)
    WHERE Hold.product = product
      AND Hold.target_date = target_date
      AND Hold.status IN (PENDING, CONFIRMED)
      AND (Hold.expires_at IS NULL OR Hold.expires_at >= now)
```

Expired holds are excluded from `committed` **immediately** at query time, regardless of whether the background `release_expired` job has updated their status to RELEASED.

### available

What can still be promised to new customers.

```
available = on_hand - committed
```

This is the value returned by `stock.available(product, target_date, position)`.

### demand

Quantity that customers want but that has no linked stock.

```
demand(product, target_date) = SUM(Hold.quantity)
    WHERE Hold.product = product
      AND Hold.target_date = target_date
      AND Hold.quant IS NULL
      AND Hold is active (same rules as committed)
```

Demand holds are created when `availability_policy = 'demand_ok'` and no stock is available. They signal to the planning layer that production is needed.

### in_transit (conceptual)

Stockman does not currently model in-transit stock as a separate quantity. However, planned Quants (those with a future `target_date`) serve a similar role:

```
in_transit(product, target_date) = SUM(Quant._quantity)
    WHERE Quant.product = product
      AND Quant.target_date > today
      AND Quant.target_date <= target_date
```

These Quants represent production that has been planned but not yet physically realized. The `realize()` operation converts them into physical stock.

---

## Shelflife Filtering

Products can declare a `shelflife` attribute (integer days, or `None`).

| shelflife | Meaning | Example |
|-----------|---------|---------|
| `None` | No expiration. All physical stock and planned stock up to target_date are valid. | Wine, hardware |
| `0` | Same-day only. Only stock produced on the target_date is valid. | Fresh croissant |
| `3` | Valid for 3 days after production. | Cake, baguette |

The filtering logic (`shelflife.filter_valid_quants`) computes a minimum production date:

```
min_production = target_date - timedelta(days=shelflife)
```

Then includes Quants where:
- Physical stock (`target_date IS NULL`): `created_at.date() >= min_production`
- Planned stock (`target_date IS NOT NULL`): `min_production <= target_date <= target_date`

When `shelflife` is `None`, all physical stock is included and planned stock up to the target date is included.

---

## Quant Lifecycle

A Quant is a quantity cache at a space-time coordinate `(product, position, target_date, batch)`.

```
                          receive() / plan()
                                |
                                v
                      +-------------------+
                      |      CREATED      |
                      |  _quantity > 0    |
                      +-------------------+
                                |
              +-----------------+-----------------+
              |                                   |
         issue() /                           realize()
         fulfill()                    (planned -> physical)
              |                                   |
              v                                   v
    +-------------------+             +-------------------+
    |     DECREMENTED   |             |   TRANSFERRED     |
    |  _quantity -= N   |             | planned zeroed,   |
    +-------------------+             | physical created  |
              |                       +-------------------+
              v
    +-------------------+
    |      EMPTY        |
    |  _quantity == 0   |
    +-------------------+
              |
         adjust()
         (correction)
              |
              v
    +-------------------+
    |   RE-ADJUSTED     |
    |  _quantity = new  |
    +-------------------+
```

Key rules:
- Quants are **never deleted**. An empty Quant (`_quantity = 0`) remains for audit.
- Quants are unique per coordinate: `(content_type, object_id, position, target_date, batch)`.
- All quantity changes go through Move creation (append-only ledger).

---

## Hold Lifecycle

```
    hold()
      |
      v
+-----------+     confirm()     +-------------+     fulfill()     +-------------+
|  PENDING  | ----------------> |  CONFIRMED  | ----------------> |  FULFILLED  |
+-----------+                   +-------------+                   +-------------+
      |                               |
      | release()                     | release()
      |                               |
      v                               v
+---------------------------------------------------+
|                    RELEASED                        |
+---------------------------------------------------+
      ^
      |
  expires_at < now  (auto-expire via release_expired)
```

### States

| State | Blocks availability? | Has linked Quant? | Terminal? |
|-------|:--------------------:|:-----------------:|:---------:|
| PENDING | Yes (if not expired) | Maybe (reservation) or No (demand) | No |
| CONFIRMED | Yes (if not expired) | Maybe | No |
| FULFILLED | No | Yes (was linked) | Yes |
| RELEASED | No | N/A | Yes |

### Two operation modes

**Reservation** (`quant IS NOT NULL`):
- Hold is linked to a specific Quant.
- The held quantity reduces `Quant.available`.
- On `fulfill()`, a negative Move is created against that Quant.

**Demand** (`quant IS NULL`):
- Hold has no linked stock -- it represents customer intent.
- Created when `availability_policy = 'demand_ok'` and no stock exists.
- Does not reduce any Quant's available (there is no Quant).
- Appears in `stock.demand()` queries.
- When production is later planned and realized, demand holds can be manually linked.
- Cannot be fulfilled directly (raises `HOLD_IS_DEMAND`).

### Expiration

- Each hold can have an `expires_at` datetime.
- An expired hold is **logically inactive** even before the background job runs.
- `Quant.held` and `Hold.objects.active()` both exclude expired holds at query time.
- The `release_expired_holds` management command (or `stock.release_expired()`) batch-updates the status to RELEASED for bookkeeping.

---

## Move Types and Their Effect on Quantities

Moves are the **only** mechanism that changes `Quant._quantity`. Every Move is immutable and append-only.

| Operation | Move delta | Effect on Quant._quantity | Typical reason |
|-----------|:----------:|:-------------------------:|----------------|
| `receive()` | `+quantity` | Increases | "Recebimento" |
| `plan()` | `+quantity` | Increases (planned Quant) | "Producao planejada" |
| `issue()` | `-quantity` | Decreases | "Saida" |
| `fulfill()` | `-hold.quantity` | Decreases | "Entrega hold:{pk}" |
| `adjust()` | `new - current` | Sets to new value | "Ajuste: {reason}" |
| `realize()` (adjust) | `actual - planned` | Corrects planned Quant | "Ajuste producao: {reason}" |
| `realize()` (transfer out) | `-actual_quantity` | Zeroes planned Quant | "Transferencia: {reason}" |
| `realize()` (transfer in) | `+actual_quantity` | Increases physical Quant | "Recebido de producao: {reason}" |

### Correction pattern

Since Moves cannot be edited or deleted, corrections follow the **reversal** pattern:

```
# Wrong: received 100, should have been 80
stock.adjust(quant, Decimal('80'), reason="Contagem fisica corrigida")
# Creates Move with delta = -20
```

---

## Batch / Lot Traceability

The `Batch` model provides traceability metadata for products with expiry or supplier tracking needs.

### Relationship

```
+----------+          batch (CharField)           +----------+
|  Batch   | <-----------------------------------  |  Quant   |
|          |          batch_ref (FK, optional)     |          |
| code     | <-----------------------------------  |          |
| expiry   |                                       | _quantity|
| supplier |                                       |          |
+----------+                                       +----------+
```

- `Quant.batch` (CharField): lightweight string key, part of the unique coordinate.
- `Quant.batch_ref` (FK to Batch): optional rich reference with metadata.
- `Batch.code` matches `Quant.batch` for lookups.

### Batch attributes

| Field | Purpose |
|-------|---------|
| `code` | Unique lot identifier (e.g., "LOT-2026-0223-A") |
| `production_date` | When the lot was produced |
| `expiry_date` | Last day the lot can be sold/used |
| `supplier` | Which supplier provided this lot |
| `notes` | Free-form observations |

### Use cases

- **FIFO picking**: Batches are ordered by `(expiry_date, production_date)`. Query `Batch.objects.active()` to find lots with remaining stock.
- **Expiry tracking**: `Batch.objects.expiring_before(date)` finds lots expiring on or before a date. `Batch.objects.expired()` finds lots past expiry.
- **Recall management**: Filter all Quants by `batch_ref` or `batch` code to locate affected stock.
- **Supplier traceability**: Filter batches by `supplier` to trace origin.

### Batch vs. Shelflife

These are complementary, not redundant:

| Mechanism | Scope | Granularity | Source of truth |
|-----------|-------|-------------|-----------------|
| `product.shelflife` | Product-level | Uniform for all units | Product model attribute |
| `Batch.expiry_date` | Lot-level | Varies per batch | Batch model record |

Shelflife filtering is applied by the availability engine automatically. Batch expiry tracking is available for querying but is not yet automatically enforced by the availability engine -- operators can use `Batch.objects.expired()` and `check_alerts()` to catch expiring stock.
