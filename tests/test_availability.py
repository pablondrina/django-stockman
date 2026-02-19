"""
Testes de Disponibilidade - Stockman/Batch Integration

Cenários testados:
1. Disponibilidade básica (quant simples)
2. Holds reduzem disponibilidade
3. Holds expirados são ignorados
4. shelflife=0 ignora estoque de dias anteriores
5. Consistência Batch.available == stock.available
6. Alternativas respeitam disponibilidade real
7. Basket bloqueia quando estoque insuficiente
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.test import Client

from catalog.models import Product, Category, Keyword
from batch.models import Batch
from stockman.models import Quant, Hold, Position
from stockman import stock
from catalog.services import get_alternative_products


@pytest.fixture
def category(db):
    return Category.objects.create(name="Test Category", slug="test-cat")


@pytest.fixture
def position(db):
    return Position.objects.get_or_create(code="TEST", defaults={"name": "Test"})[0]


@pytest.fixture
def product_perishable(db, category):
    """Produto perecível (shelflife=0)."""
    return Product.objects.create(
        name="Test Perishable",
        slug="test-perishable",
        category=category,
        price=Decimal("10.00"),
        is_active=True,
        is_batch_produced=True,
        can_be_sold_next_day=False,
        shelflife=0,
    )


@pytest.fixture
def product_durable(db, category):
    """Produto durável (shelflife=3)."""
    return Product.objects.create(
        name="Test Durable",
        slug="test-durable",
        category=category,
        price=Decimal("15.00"),
        is_active=True,
        is_batch_produced=True,
        can_be_sold_next_day=True,
        shelflife=3,
    )


def create_batch_with_stock(product, position, date, produced):
    """Helper: cria Batch + Quant consistentes."""
    ct = ContentType.objects.get_for_model(product)

    # Criar Batch
    batch = Batch.objects.create(
        product=product,
        date=date,
        planned=produced + 10,
        produced=produced,
    )

    # Deletar Quant criado pelo signal (se existir) e criar manualmente
    Quant.objects.filter(
        content_type=ct, object_id=product.pk, target_date=date
    ).delete()

    quant = Quant.objects.create(
        content_type=ct,
        object_id=product.pk,
        position=position,
        target_date=date,
        _quantity=Decimal(str(produced)),
    )

    return batch, quant


class TestBasicAvailability:
    """Testes de disponibilidade básica."""

    def test_available_with_quant(self, db, product_perishable, position):
        """Disponibilidade igual à quantidade no Quant."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("50"),
        )

        available = stock.available(product_perishable, today)
        assert available == Decimal("50")

    def test_available_zero_without_quant(self, db, product_perishable):
        """Disponibilidade zero sem Quant."""
        today = date.today()
        available = stock.available(product_perishable, today)
        assert available == Decimal("0")


class TestHoldsAffectAvailability:
    """Testes de holds reduzindo disponibilidade."""

    def test_pending_hold_reduces_availability(self, db, product_perishable, position):
        """Hold PENDING reduz disponibilidade."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        quant = Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("50"),
        )

        Hold.objects.create(
            quant=quant,
            content_type=ct,
            object_id=product_perishable.pk,
            target_date=today,
            quantity=Decimal("20"),
            status="pending",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        available = stock.available(product_perishable, today)
        assert available == Decimal("30")

    def test_expired_hold_ignored(self, db, product_perishable, position):
        """Hold EXPIRADO é ignorado."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        quant = Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("50"),
        )

        Hold.objects.create(
            quant=quant,
            content_type=ct,
            object_id=product_perishable.pk,
            target_date=today,
            quantity=Decimal("20"),
            status="pending",
            expires_at=timezone.now() - timedelta(hours=1),
        )

        available = stock.available(product_perishable, today)
        assert available == Decimal("50")

    def test_released_hold_ignored(self, db, product_perishable, position):
        """Hold RELEASED é ignorado."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        quant = Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("50"),
        )

        Hold.objects.create(
            quant=quant,
            content_type=ct,
            object_id=product_perishable.pk,
            target_date=today,
            quantity=Decimal("20"),
            status="released",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        available = stock.available(product_perishable, today)
        assert available == Decimal("50")


class TestShelflife:
    """Testes de shelflife."""

    def test_shelflife_zero_ignores_previous_days(
        self, db, product_perishable, position
    ):
        """shelflife=0 ignora estoque de dias anteriores."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        ct = ContentType.objects.get_for_model(product_perishable)

        Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=yesterday,
            _quantity=Decimal("100"),
        )

        Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("30"),
        )

        available = stock.available(product_perishable, today)
        assert available == Decimal("30")

    def test_shelflife_includes_valid_stock(self, db, product_durable, position):
        """shelflife>0 inclui estoque dentro da validade."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        ct = ContentType.objects.get_for_model(product_durable)

        Quant.objects.create(
            content_type=ct,
            object_id=product_durable.pk,
            position=position,
            target_date=yesterday,
            _quantity=Decimal("50"),
        )

        Quant.objects.create(
            content_type=ct,
            object_id=product_durable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("30"),
        )

        available = stock.available(product_durable, today)
        assert available == Decimal("80")


class TestBatchConsistency:
    """Testes Batch <-> Stockman."""

    def test_batch_available_equals_stock_available(
        self, db, product_perishable, position
    ):
        """Batch.available == stock.available."""
        today = date.today()

        batch, quant = create_batch_with_stock(product_perishable, position, today, 45)

        assert batch.available == stock.available(product_perishable, today)
        assert batch.available == 45


class TestBasketValidation:
    """Testes de validação no basket."""

    def test_basket_rejects_insufficient_stock(self, db, product_perishable, position):
        """Basket rejeita quando estoque insuficiente."""
        import json
        from salesman.basket.models import Basket

        today = date.today()

        Basket.objects.all().delete()

        # Criar Batch + Quant com 10 unidades
        create_batch_with_stock(product_perishable, position, today, 10)

        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 50,
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert "stock_error" in data
        assert data["stock_error"]["available"] == 10
        assert data["stock_error"]["requested"] == 50

    def test_basket_accepts_available_stock(self, db, product_perishable, position):
        """Basket aceita quando estoque suficiente."""
        import json
        from salesman.basket.models import Basket

        today = date.today()

        Basket.objects.all().delete()

        # Criar Batch + Quant com 50 unidades
        create_batch_with_stock(product_perishable, position, today, 50)

        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 30,
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 201


class TestAlternativesRespectAvailability:
    """Testes de alternativas."""

    def test_alternative_quantity_limited(
        self, db, product_perishable, position, category
    ):
        """Quantidade de alternativa <= disponibilidade."""
        today = date.today()

        # Criar produto alternativo com Batch
        alt_product = Product.objects.create(
            name="Alt Product",
            slug="alt-product",
            category=category,
            price=Decimal("12.00"),
            is_active=True,
            is_batch_produced=True,
            shelflife=0,
        )

        # Criar Batch + Quant para alternativa com 15 unidades
        create_batch_with_stock(alt_product, position, today, 15)

        # Criar keyword comum
        kw = Keyword.objects.create(name="test-kw", slug="test-kw")
        product_perishable.keywords.add(kw)
        alt_product.keywords.add(kw)

        alternatives = get_alternative_products(product_perishable, today, limit=5)

        alt_found = next((a for a in alternatives if a["product"] == alt_product), None)
        assert alt_found is not None
        assert alt_found["available"] == 15

    def test_basket_alternative_action_respects_availability(
        self, db, product_perishable, position, category
    ):
        """Ação de alternativa não sugere mais que disponível."""
        import json
        from salesman.basket.models import Basket

        today = date.today()

        Basket.objects.all().delete()

        # Criar Batch + Quant para produto principal com 5 unidades
        create_batch_with_stock(product_perishable, position, today, 5)

        # Criar produto alternativo com 8 unidades
        alt_product = Product.objects.create(
            name="Alt Product 2",
            slug="alt-product-2",
            category=category,
            price=Decimal("12.00"),
            is_active=True,
            is_batch_produced=True,
            shelflife=0,
        )

        create_batch_with_stock(alt_product, position, today, 8)

        # Criar keyword comum
        kw = Keyword.objects.create(name="test-kw2", slug="test-kw2")
        product_perishable.keywords.add(kw)
        alt_product.keywords.add(kw)

        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 20,  # Pede 20, só tem 5
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()

        # Verificar alternativas
        alternatives = data.get("actions", {}).get("alternatives", [])
        for alt in alternatives:
            if alt["product"]["id"] == alt_product.pk:
                # Quantidade sugerida deve ser <= 8 (disponível)
                assert alt["body"]["quantity"] <= 8
                assert alt["body"]["quantity"] <= alt["product"]["available"]


# =============================================================================
# CENÁRIOS ADICIONAIS
# =============================================================================


class TestConcurrentHolds:
    """Testes de holds concorrentes (race conditions)."""

    def test_multiple_simultaneous_holds(self, db, product_perishable, position):
        """Múltiplos holds simultâneos são somados corretamente."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        quant = Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("100"),
        )

        # Simular 5 clientes adicionando ao carrinho simultaneamente
        for i in range(5):
            Hold.objects.create(
                quant=quant,
                content_type=ct,
                object_id=product_perishable.pk,
                target_date=today,
                quantity=Decimal("15"),
                status="pending",
                expires_at=timezone.now() + timedelta(hours=1),
            )

        available = stock.available(product_perishable, today)
        # 100 - (5 * 15) = 25
        assert available == Decimal("25")

    def test_holds_from_different_baskets(self, db, product_perishable, position):
        """Holds de diferentes baskets são somados."""
        import json
        from salesman.basket.models import Basket

        today = date.today()

        Basket.objects.all().delete()
        create_batch_with_stock(product_perishable, position, today, 50)

        # Cliente 1: adiciona 20
        client1 = Client()
        response1 = client1.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 20,
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )
        assert response1.status_code == 201

        # Cliente 2: tenta adicionar 40 (só tem 30 disponíveis)
        client2 = Client()
        response2 = client2.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 40,
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )

        # Deve falhar porque 50 - 20 = 30 disponíveis
        assert response2.status_code == 400
        data = response2.json()
        assert data["stock_error"]["available"] == 30


class TestEdgeCases:
    """Testes de casos extremos."""

    def test_zero_quantity_quant(self, db, product_perishable, position):
        """Quant com quantidade zero."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("0"),
        )

        available = stock.available(product_perishable, today)
        assert available == Decimal("0")

    def test_hold_equals_quant(self, db, product_perishable, position):
        """Hold igual ao Quant resulta em disponibilidade zero."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        quant = Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("50"),
        )

        Hold.objects.create(
            quant=quant,
            content_type=ct,
            object_id=product_perishable.pk,
            target_date=today,
            quantity=Decimal("50"),
            status="pending",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        available = stock.available(product_perishable, today)
        assert available == Decimal("0")

    def test_basket_exact_quantity(self, db, product_perishable, position):
        """Basket aceita quantidade exata disponível."""
        import json
        from salesman.basket.models import Basket

        today = date.today()

        Basket.objects.all().delete()
        create_batch_with_stock(product_perishable, position, today, 25)

        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 25,  # Exatamente o disponível
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 201

    def test_negative_availability_prevented(self, db, product_perishable, position):
        """Sistema não permite disponibilidade negativa em operações normais."""
        import json
        from salesman.basket.models import Basket

        today = date.today()

        Basket.objects.all().delete()
        create_batch_with_stock(product_perishable, position, today, 10)

        # Tentar adicionar mais que disponível
        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 100,
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )

        # Deve bloquear
        assert response.status_code == 400


class TestFutureDates:
    """Testes com datas futuras."""

    def test_future_date_no_stock(self, db, product_perishable, position):
        """Data futura sem produção retorna zero."""
        today = date.today()
        future = today + timedelta(days=5)

        # Criar estoque apenas para hoje
        create_batch_with_stock(product_perishable, position, today, 50)

        available = stock.available(product_perishable, future)
        assert available == Decimal("0")

    def test_future_date_with_batch_no_production(
        self, db, product_perishable, position
    ):
        """Data futura com Batch planejado mas não produzido."""
        today = date.today()
        tomorrow = today + timedelta(days=1)

        # Criar Batch para amanhã (planejado, não produzido)
        Batch.objects.create(
            product=product_perishable,
            date=tomorrow,
            planned=50,
            produced=0,  # Não produzido ainda
        )

        # stock.available retorna 0 (sem Quant)
        available = stock.available(product_perishable, tomorrow)
        assert available == Decimal("0")

        # Mas Batch existe com planejamento
        batch = Batch.objects.get(product=product_perishable, date=tomorrow)
        assert batch.planned == 50

    def test_basket_future_date(self, db, product_perishable, position):
        """Basket para data futura sem estoque é rejeitado."""
        import json
        from salesman.basket.models import Basket

        today = date.today()
        future = today + timedelta(days=3)

        Basket.objects.all().delete()

        # Sem estoque para data futura
        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 10,
                    "extra": {"target_date": str(future)},
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400


class TestMultipleProducts:
    """Testes com múltiplos produtos."""

    def test_different_products_independent(
        self, db, product_perishable, product_durable, position
    ):
        """Disponibilidade de produtos diferentes é independente."""
        today = date.today()

        create_batch_with_stock(product_perishable, position, today, 30)
        create_batch_with_stock(product_durable, position, today, 50)

        avail_perishable = stock.available(product_perishable, today)
        avail_durable = stock.available(product_durable, today)

        assert avail_perishable == Decimal("30")
        assert avail_durable == Decimal("50")

    def test_hold_affects_only_target_product(
        self, db, product_perishable, product_durable, position
    ):
        """Hold em um produto não afeta outro."""
        today = date.today()
        ct_perishable = ContentType.objects.get_for_model(product_perishable)

        batch1, quant1 = create_batch_with_stock(
            product_perishable, position, today, 30
        )
        batch2, quant2 = create_batch_with_stock(product_durable, position, today, 50)

        # Hold apenas no perishable
        Hold.objects.create(
            quant=quant1,
            content_type=ct_perishable,
            object_id=product_perishable.pk,
            target_date=today,
            quantity=Decimal("20"),
            status="pending",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        # Perishable: 30 - 20 = 10
        assert stock.available(product_perishable, today) == Decimal("10")

        # Durable: ainda 50 (não afetado)
        assert stock.available(product_durable, today) == Decimal("50")


class TestHoldExpiration:
    """Testes de expiração de holds."""

    def test_hold_about_to_expire(self, db, product_perishable, position):
        """Hold prestes a expirar ainda reduz disponibilidade."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        quant = Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("50"),
        )

        # Hold expira em 1 segundo
        Hold.objects.create(
            quant=quant,
            content_type=ct,
            object_id=product_perishable.pk,
            target_date=today,
            quantity=Decimal("20"),
            status="pending",
            expires_at=timezone.now() + timedelta(seconds=1),
        )

        # Ainda ativo
        available = stock.available(product_perishable, today)
        assert available == Decimal("30")

    def test_hold_no_expiration(self, db, product_perishable, position):
        """Hold sem expiração (confirmed) sempre reduz disponibilidade."""
        today = date.today()
        ct = ContentType.objects.get_for_model(product_perishable)

        quant = Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("50"),
        )

        # Hold confirmado sem expiração
        Hold.objects.create(
            quant=quant,
            content_type=ct,
            object_id=product_perishable.pk,
            target_date=today,
            quantity=Decimal("20"),
            status="confirmed",
            expires_at=None,  # Sem expiração
        )

        available = stock.available(product_perishable, today)
        assert available == Decimal("30")


class TestAlternativesComplex:
    """Testes complexos de alternativas."""

    def test_no_alternatives_when_no_keywords(
        self, db, product_perishable, position, category
    ):
        """Sem keywords, busca alternativas da mesma categoria."""
        today = date.today()

        # Criar produto sem keywords
        product_no_kw = Product.objects.create(
            name="No Keywords",
            slug="no-keywords",
            category=category,
            price=Decimal("10.00"),
            is_active=True,
            is_batch_produced=True,
            shelflife=0,
        )

        # Criar outro produto da mesma categoria
        alt_same_cat = Product.objects.create(
            name="Same Category",
            slug="same-category",
            category=category,
            price=Decimal("11.00"),
            is_active=True,
            is_batch_produced=True,
            shelflife=0,
        )
        create_batch_with_stock(alt_same_cat, position, today, 20)

        alternatives = get_alternative_products(product_no_kw, today, limit=5)

        # Deve encontrar alternativa da mesma categoria
        assert len(alternatives) > 0
        alt_names = [a["name"] for a in alternatives]
        assert "Same Category" in alt_names

    def test_alternatives_sorted_by_availability(
        self, db, product_perishable, position, category
    ):
        """Alternativas ordenadas por disponibilidade (maior primeiro)."""
        today = date.today()

        # Criar 3 produtos com diferentes disponibilidades
        products = []
        for i, qty in enumerate([10, 50, 25]):
            p = Product.objects.create(
                name=f"Alt {i}",
                slug=f"alt-{i}",
                category=category,
                price=Decimal("10.00"),
                is_active=True,
                is_batch_produced=True,
                shelflife=0,
            )
            create_batch_with_stock(p, position, today, qty)
            products.append(p)

        # Keyword comum
        kw = Keyword.objects.create(name="sort-test", slug="sort-test")
        product_perishable.keywords.add(kw)
        for p in products:
            p.keywords.add(kw)

        alternatives = get_alternative_products(product_perishable, today, limit=5)

        # Deve estar ordenado: 50, 25, 10
        availabilities = [
            a["available"] for a in alternatives if a["name"].startswith("Alt")
        ]
        assert availabilities == sorted(availabilities, reverse=True)

    def test_alternatives_exclude_self(self, db, product_perishable, position):
        """Alternativas não incluem o próprio produto."""
        today = date.today()

        create_batch_with_stock(product_perishable, position, today, 30)

        kw = Keyword.objects.create(name="self-test", slug="self-test")
        product_perishable.keywords.add(kw)

        alternatives = get_alternative_products(product_perishable, today, limit=5)

        # Não deve incluir o próprio produto
        alt_ids = [a["product"].pk for a in alternatives]
        assert product_perishable.pk not in alt_ids


class TestPreorder:
    """Testes de pré-venda (encomenda)."""

    def test_preorder_uses_planned(self, db, product_perishable, position):
        """Encomenda usa Batch.planned, não estoque real."""
        from catalog.services import get_product_availability

        today = date.today()
        tomorrow = today + timedelta(days=1)

        # Batch para amanhã: planejado 50, não produzido
        Batch.objects.create(
            product=product_perishable,
            date=tomorrow,
            planned=50,
            produced=0,
        )

        availability = get_product_availability(product_perishable, tomorrow)

        assert availability["is_preorder"] == True
        assert availability["available"] == 50  # Planejado
        assert availability["planned"] == 50
        assert availability["produced"] == 0

    def test_preorder_respects_committed(self, db, product_perishable, position):
        """Encomenda desconta reservas existentes."""
        from catalog.services import get_product_availability
        from stockman.models import Hold

        today = date.today()
        tomorrow = today + timedelta(days=1)
        ct = ContentType.objects.get_for_model(product_perishable)

        # Batch para amanhã
        batch = Batch.objects.create(
            product=product_perishable,
            date=tomorrow,
            planned=50,
            produced=0,
        )

        # Criar Quant futuro (necessário para Hold)
        quant = Quant.objects.create(
            content_type=ct,
            object_id=product_perishable.pk,
            position=position,
            target_date=tomorrow,
            _quantity=Decimal("0"),  # Ainda não produzido
        )

        # Hold de 20 unidades para amanhã
        Hold.objects.create(
            quant=quant,
            content_type=ct,
            object_id=product_perishable.pk,
            target_date=tomorrow,
            quantity=Decimal("20"),
            status="pending",
            expires_at=timezone.now() + timedelta(days=1),
        )

        availability = get_product_availability(product_perishable, tomorrow)

        # 50 planejado - 20 reservado = 30 disponível
        assert availability["available"] == 30
        assert availability["committed"] == 20

    def test_today_uses_real_stock(self, db, product_perishable, position):
        """Venda hoje usa estoque real, não planejado."""
        from catalog.services import get_product_availability

        today = date.today()

        # Batch: planejado 50, produzido 30
        create_batch_with_stock(product_perishable, position, today, 30)

        availability = get_product_availability(product_perishable, today)

        assert availability["is_preorder"] == False
        assert availability["available"] == 30  # Estoque real
        assert availability["planned"] == 40  # planned = produced + 10 (helper)
        assert availability["produced"] == 30

    def test_basket_preorder_future_date(self, db, product_perishable, position):
        """Basket aceita encomenda para data futura com planejamento."""
        import json
        from salesman.basket.models import Basket

        today = date.today()
        tomorrow = today + timedelta(days=1)

        Basket.objects.all().delete()

        # Batch para amanhã (planejado, não produzido)
        Batch.objects.create(
            product=product_perishable,
            date=tomorrow,
            planned=50,
            produced=0,
        )

        # Registrar planejamento no Stockman (a arquitetura SIREL requer isso)
        stock.plan(
            Decimal("50"),
            product_perishable,
            tomorrow,
            reason="Planejamento para teste",
        )

        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 30,  # Menos que planejado
                    "extra": {"target_date": str(tomorrow)},
                }
            ),
            content_type="application/json",
        )

        # Deve aceitar baseado no planejamento
        assert response.status_code == 201

    def test_basket_preorder_exceeds_planned(self, db, product_perishable, position):
        """Basket rejeita encomenda que excede planejamento."""
        import json
        from salesman.basket.models import Basket

        today = date.today()
        tomorrow = today + timedelta(days=1)

        Basket.objects.all().delete()

        # Batch para amanhã: apenas 30 planejados
        Batch.objects.create(
            product=product_perishable,
            date=tomorrow,
            planned=30,
            produced=0,
        )

        # Registrar planejamento no Stockman (a arquitetura SIREL requer isso)
        stock.plan(
            Decimal("30"),
            product_perishable,
            tomorrow,
            reason="Planejamento para teste",
        )

        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 50,  # Mais que planejado
                    "extra": {"target_date": str(tomorrow)},
                }
            ),
            content_type="application/json",
        )

        # Deve rejeitar
        assert response.status_code == 400
        data = response.json()
        assert data["stock_error"]["available"] == 30
        assert data["stock_error"]["requested"] == 50


class TestProductTypes:
    """Testes para diferentes tipos de produtos."""

    def test_type_a_batch_produced_after_production(
        self, db, product_perishable, position
    ):
        """Tipo A: Lote diário após produção usa estoque real."""
        from catalog.services import get_product_availability

        today = date.today()

        # Batch produzido (saiu do forno)
        create_batch_with_stock(product_perishable, position, today, 30)

        availability = get_product_availability(product_perishable, today)

        assert availability["product_type"] == "batch"
        assert availability["status"] == "produced"
        assert availability["available"] == 30
        assert availability["is_preorder"] == False

    def test_type_a_batch_awaiting_production(self, db, product_perishable, position):
        """Tipo A: Lote diário ANTES da produção (ainda no forno)."""
        from catalog.services import get_product_availability

        today = date.today()

        # Batch planejado mas não produzido (ainda no forno)
        Batch.objects.create(
            product=product_perishable,
            date=today,
            planned=50,
            produced=0,  # Não saiu do forno ainda
        )

        availability = get_product_availability(product_perishable, today)

        assert availability["product_type"] == "batch"
        assert availability["status"] == "awaiting_production"
        assert availability["available"] == 50  # Pode encomendar baseado no planejado
        assert availability["is_preorder"] == True  # Tratado como encomenda

    def test_type_b_on_demand(self, db, category, position):
        """Tipo B: Sob demanda (café) sempre disponível."""
        from catalog.services import get_product_availability

        today = date.today()

        # Produto sob demanda (não é batch)
        coffee = Product.objects.create(
            name="Café Expresso",
            slug="cafe-expresso",
            category=category,
            price=Decimal("5.00"),
            is_active=True,
            is_batch_produced=False,  # Não é produzido em lote
            shelflife=None,
        )

        availability = get_product_availability(coffee, today)

        assert availability["product_type"] == "on_demand"
        assert availability["status"] == "always_available"
        assert availability["available"] == 999
        assert availability["is_preorder"] == False

    def test_type_c_resale_with_stock(self, db, category, position):
        """Tipo C: Revenda com estoque."""
        from catalog.services import get_product_availability

        today = date.today()

        # Produto de revenda (não é batch)
        jam = Product.objects.create(
            name="Geleia Artesanal",
            slug="geleia-artesanal",
            category=category,
            price=Decimal("25.00"),
            is_active=True,
            is_batch_produced=False,
            shelflife=365,  # Validade longa
        )

        ct = ContentType.objects.get_for_model(jam)

        # Estoque manual (revenda)
        Quant.objects.create(
            content_type=ct,
            object_id=jam.pk,
            position=position,
            target_date=today,
            _quantity=Decimal("15"),
        )

        availability = get_product_availability(jam, today)

        assert availability["product_type"] == "revenda"
        assert availability["status"] == "in_stock"
        assert availability["available"] == 15
        assert availability["is_preorder"] == False

    def test_type_c_resale_without_stock(self, db, category, position):
        """Tipo C sem estoque vira Tipo B (sob demanda)."""
        from catalog.services import get_product_availability

        today = date.today()

        # Produto de revenda sem estoque
        soda = Product.objects.create(
            name="Refrigerante",
            slug="refrigerante",
            category=category,
            price=Decimal("8.00"),
            is_active=True,
            is_batch_produced=False,
            shelflife=180,
        )

        # Sem Quant criado
        availability = get_product_availability(soda, today)

        # Sem estoque, trata como sob demanda
        assert availability["product_type"] == "on_demand"
        assert availability["status"] == "always_available"


class TestAwaitingProduction:
    """Testes específicos para 'ainda no forno'."""

    def test_basket_accepts_awaiting_production(self, db, product_perishable, position):
        """Basket aceita compra mesmo antes de produzir (encomenda do dia)."""
        import json
        from salesman.basket.models import Basket

        today = date.today()

        Basket.objects.all().delete()

        # Batch planejado mas não produzido
        Batch.objects.create(
            product=product_perishable,
            date=today,
            planned=50,
            produced=0,
        )

        # Registrar planejamento no Stockman (a arquitetura SIREL requer isso)
        stock.plan(
            Decimal("50"), product_perishable, today, reason="Planejamento para teste"
        )

        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 30,
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )

        # Deve aceitar como encomenda do dia
        assert response.status_code == 201

    def test_basket_rejects_exceeding_planned(self, db, product_perishable, position):
        """Basket rejeita se excede planejado (mesmo antes de produzir)."""
        import json
        from salesman.basket.models import Basket

        today = date.today()

        Basket.objects.all().delete()

        # Batch planejado mas não produzido
        Batch.objects.create(
            product=product_perishable,
            date=today,
            planned=30,
            produced=0,
        )

        # Registrar planejamento no Stockman (a arquitetura SIREL requer isso)
        stock.plan(
            Decimal("30"), product_perishable, today, reason="Planejamento para teste"
        )

        client = Client()
        response = client.post(
            "/api/shop/basket/",
            data=json.dumps(
                {
                    "product_type": "catalog.Product",
                    "product_id": product_perishable.pk,
                    "quantity": 50,  # Mais que planejado
                    "extra": {"target_date": str(today)},
                }
            ),
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["stock_error"]["available"] == 30

    def test_status_changes_after_production(self, db, product_perishable, position):
        """Status muda de awaiting_production para produced."""
        from catalog.services import get_product_availability

        today = date.today()

        # Criar Batch não produzido
        batch = Batch.objects.create(
            product=product_perishable,
            date=today,
            planned=50,
            produced=0,
        )

        # Antes da produção
        avail1 = get_product_availability(product_perishable, today)
        assert avail1["status"] == "awaiting_production"

        # Simular produção (signal do Batch cria Quant automaticamente)
        batch.produced = 45
        batch.save()

        # Depois da produção
        avail2 = get_product_availability(product_perishable, today)
        assert avail2["status"] == "produced"
        assert avail2["available"] == 45
