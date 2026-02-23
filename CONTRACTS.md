# Stockman Contracts

Public API, invariants, and integration boundaries for `django-stockman` (v0.2.0).

---

## Public API

The single entry point is the `Stock` class, used as a static facade:

```python
from stockman import stock, StockError
```

All state-changing methods run inside `transaction.atomic()` with appropriate row-level locking (`select_for_update`).

### Movements

| Method | Signature | Description |
|--------|-----------|-------------|
| `receive` | `(quantity, product, position=None, target_date=None, batch='', reference=None, user=None, reason='Recebimento', **metadata) -> Quant` | Stock entry. Creates or finds Quant at the given coordinate, then appends a positive Move. |
| `issue` | `(quantity, quant, reference=None, user=None, reason='Saida') -> Move` | Stock exit. Locks the Quant, verifies availability, appends a negative Move. Raises `INSUFFICIENT_QUANTITY` if not enough. |
| `adjust` | `(quant, new_quantity, reason, user=None) -> Move or None` | Inventory correction. Computes `delta = new_quantity - current` and appends a Move. Returns `None` when delta is zero. Raises `REASON_REQUIRED` if reason is empty. |

### Holds (reservation lifecycle)

| Method | Signature | Description |
|--------|-----------|-------------|
| `hold` | `(quantity, product, target_date=None, purpose=None, expires_at=None, **metadata) -> str` | Creates a hold. Returns `"hold:{pk}"`. Behavior depends on the product's `availability_policy`: `stock_only`, `planned_ok` (default), or `demand_ok`. Raises `INSUFFICIENT_AVAILABLE` when policy forbids demand creation. |
| `confirm` | `(hold_id) -> Hold` | Transition: PENDING -> CONFIRMED. Raises `INVALID_STATUS` if not PENDING. |
| `release` | `(hold_id, reason='Liberado') -> Hold` | Transition: PENDING or CONFIRMED -> RELEASED. Records `resolved_at` and reason. |
| `fulfill` | `(hold_id, reference=None, user=None) -> Move` | Transition: CONFIRMED -> FULFILLED. Creates a negative Move against the linked Quant. Raises `HOLD_IS_DEMAND` if quant is None. |
| `release_expired` | `() -> int` | Batch-releases expired holds using `select_for_update(skip_locked=True)`. Safe for concurrent execution. Returns count released. |

### Planning (production scheduling)

| Method | Signature | Description |
|--------|-----------|-------------|
| `plan` | `(quantity, product, target_date, position=None, reference=None, user=None, reason='Producao planejada', **metadata) -> Quant` | Shortcut for `receive()` with a mandatory future `target_date`. Creates a planned Quant. |
| `replan` | `(quantity, product, target_date, reason, user=None) -> Quant` | Adjusts an existing planned Quant to the new quantity. Raises `QUANT_NOT_FOUND` if no plan exists. |
| `realize` | `(product, target_date, actual_quantity, to_position, user=None, reason='Producao realizada') -> Quant` | Converts planned stock into physical stock. Adjusts if actual differs from plan, transfers quantity via two Moves (out of planned, into physical), and migrates active holds to the physical Quant. |

### Queries (read-only, no locking)

| Method | Signature | Description |
|--------|-----------|-------------|
| `available` | `(product, target_date=None, position=None) -> Decimal` | `valid_on_hand - active_holds` for the given coordinates. Applies shelflife filtering. |
| `demand` | `(product, target_date) -> Decimal` | Sum of active hold quantities where `quant IS NULL` (unlinked demand). |
| `committed` | `(product, target_date=None) -> Decimal` | Sum of all active hold quantities (both linked and unlinked). |
| `get_quant` | `(product, position=None, target_date=None, batch='') -> Quant or None` | Exact coordinate lookup. |
| `list_quants` | `(product=None, position=None, include_future=True, include_empty=False) -> QuerySet` | Filtered listing. |

---

## Invariants

### 1. Quant quantities are consistent with Move history

`Quant._quantity` is a **cache** updated atomically by `Move.save()` using `F('_quantity') + delta`. The true source of truth is the Move ledger. At any point:

```
Quant._quantity == SUM(Move.delta) for all moves on that quant
```

`Quant.recalculate()` recomputes from Moves and corrects the cache if drifted.

### 2. Moves are append-only (ledger)

- `Move.save()` raises `ValueError` if the instance already has a PK (update attempt).
- `Move.delete()` raises `ValueError` unconditionally.
- Corrections are new Moves with inverse delta, never edits.

### 3. Holds are TTL-based and auto-expire

- Each Hold can have an `expires_at` timestamp.
- `Hold.objects.active()` excludes holds where `expires_at < now`, even if their status field still reads PENDING or CONFIRMED.
- `Quant.held` and `Quant.available` always ignore expired holds in their computation, independent of whether the `release_expired` background job has run.
- `stock.release_expired()` (or the `release_expired_holds` management command) bulk-transitions expired holds to RELEASED status, using batched `select_for_update(skip_locked=True)` for safe concurrency.

### 4. Available = on_hand - committed

| Term | Definition |
|------|------------|
| **on_hand** | `Quant._quantity` -- the total physical (or planned) quantity at a coordinate, computed as the running sum of all Moves on that Quant. |
| **committed** | Sum of `Hold.quantity` for all **active** holds (status PENDING or CONFIRMED, and not expired) linked to a product/date. |
| **available** | `on_hand - committed` -- the quantity that can still be promised to new customers. |

The `available()` query method also applies **shelflife filtering**: Quants whose production date is too old for the requested target date are excluded from `on_hand` before subtracting committed.

---

## Idempotency

| Operation | Idempotent? | Notes |
|-----------|:-----------:|-------|
| `receive` | **No** | Every call appends a new Move and increments quantity. |
| `issue` | **No** | Every call appends a new Move and decrements quantity. |
| `adjust` | **Yes** (effectively) | If the target quantity matches current, returns `None` and creates no Move. Repeated calls with the same `new_quantity` are safe. |
| `hold` | **No** | Every call creates a new Hold record. Callers must deduplicate via `purpose` (GenericForeignKey). |
| `confirm` | **Yes** (effectively) | Second call on an already-CONFIRMED hold raises `INVALID_STATUS`. No partial side effects. |
| `release` | **Yes** (effectively) | Second call on an already-RELEASED hold raises `INVALID_STATUS`. No partial side effects. |
| `fulfill` | **Yes** (effectively) | Second call on an already-FULFILLED hold raises `INVALID_STATUS`. No partial side effects. |
| `release_expired` | **Yes** | Already-released holds are skipped; running twice has the same outcome. |
| `plan` | **No** | Delegates to `receive`. |
| `replan` | **Yes** (effectively) | Same behavior as `adjust`. |
| `realize` | **No** | Creates multiple Moves and migrates holds. Should only be called once per planned Quant. |
| `available`, `demand`, `committed` | **Yes** | Read-only queries. |

---

## Integration Points

### Protocols (defined by Stockman)

1. **`SkuValidator`** (`stockman.protocols.sku`)
   - Methods: `validate_sku(sku) -> SkuValidationResult`, `validate_skus(skus) -> dict`, `get_sku_info(sku) -> SkuInfo | None`, `search_skus(query, limit, include_inactive) -> list[SkuInfo]`
   - Loaded at runtime from the dotted path in `STOCKMAN["SKU_VALIDATOR"]`.
   - Adapter: `stockman.adapters.offerman` loads the configured class.
   - Noop adapter: `stockman.adapters.noop.NoopSkuValidator` for dev/test.

2. **`ProductionBackend`** (`stockman.protocols.production`)
   - Methods: `request_production(request) -> ProductionResult`, `check_status(request_id) -> ProductionStatus | None`, `cancel_request(request_id, reason) -> ProductionResult`, `list_pending(sku, target_date) -> list[ProductionStatus]`
   - Adapter: `stockman.adapters.craftsman.CraftsmanBackend` integrates with the Craftsman manufacturing module.

### Adapters (provided by Stockman)

| Adapter | Protocol | External System | Factory |
|---------|----------|-----------------|---------|
| `offerman.py` | `SkuValidator` | Offerman (product catalog) | `get_sku_validator()` |
| `craftsman.py` | `ProductionBackend` | Craftsman (manufacturing) | `get_production_backend()` |
| `noop.py` | `SkuValidator` | None (dev/test stub) | Direct instantiation |

### Configuration (`settings.STOCKMAN`)

| Key | Type | Default | Purpose |
|-----|------|---------|---------|
| `SKU_VALIDATOR` | `str` | `""` | Dotted path to SkuValidator implementation |
| `HOLD_TTL_MINUTES` | `int` | `0` | Default hold TTL (0 = no expiration) |
| `EXPIRED_BATCH_SIZE` | `int` | `200` | Batch size for `release_expired` processing |
| `VALIDATE_INPUT_SKUS` | `bool` | `True` | Whether to validate SKUs before stock operations |

### Product protocol (duck-typed)

Stockman reads optional attributes from product objects:

| Attribute | Type | Default | Used by |
|-----------|------|---------|---------|
| `shelflife` | `int or None` | `None` | `filter_valid_quants()` -- days the product stays valid after production. `None` = no expiration, `0` = same-day only. |
| `availability_policy` | `str` | `"planned_ok"` | `hold()` -- one of `stock_only`, `planned_ok`, `demand_ok`. |

---

## What is NOT Stockman's Job

- **Pricing**: Stockman has no concept of price, cost, or margin. Price management belongs to Offerman or whatever catalog system is in use.
- **Product catalog**: Stockman references products via Django's `ContentType` + `object_id` (GenericForeignKey). It does not define, store, or manage product master data, categories, or attributes. That belongs to Offerman.
- **Order management**: Stockman provides holds (reservations) but does not manage orders, carts, checkout flows, payments, or fulfillment orchestration. Those belong to Salesman or equivalent order management systems.
- **Production execution**: Stockman can request production via the `ProductionBackend` protocol and track its status, but the actual recipe management, work order execution, material consumption, and shop-floor scheduling belong to Craftsman.
- **Shipping / logistics**: Stockman tracks where stock is (Positions) and how much, but does not manage shipping carriers, tracking numbers, or delivery routes.
