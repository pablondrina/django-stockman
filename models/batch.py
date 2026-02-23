"""
Batch model — lot/batch traceability for products with expiry.

First-class inventory solutions require batch-level tracking for:
- Products with shelf life (food, pharmaceuticals, cosmetics)
- Supplier traceability (which supplier delivered this lot?)
- Recall management (find all stock from a specific batch)
- FIFO enforcement based on production/expiry date

Usage:
    batch = Batch.objects.create(
        code="LOT-2026-0223-A",
        product_type=ct, product_id=product.pk,
        production_date=date.today(),
        expiry_date=date.today() + timedelta(days=3),
        supplier="Fornecedor ABC",
    )

    stock.receive(50, product, vitrine, batch=batch.code)
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class BatchQuerySet(models.QuerySet):
    """Custom QuerySet for Batch with convenience filters."""

    def active(self):
        """Batches with remaining stock (at least one non-empty quant)."""
        return self.filter(quants___quantity__gt=0).distinct()

    def expiring_before(self, date):
        """Batches expiring on or before the given date."""
        return self.filter(expiry_date__lte=date, expiry_date__isnull=False)

    def expired(self):
        """Batches past their expiry date."""
        from datetime import date as date_cls
        return self.expiring_before(date_cls.today())

    def for_product(self, product):
        """Filter batches for a specific product."""
        ct = ContentType.objects.get_for_model(product)
        return self.filter(product_type=ct, product_id=product.pk)


class Batch(models.Model):
    """
    Batch/lot for traceability of products with expiry.

    A Batch groups stock by production lot. Each Quant can optionally
    reference a Batch via the batch CharField (Batch.code = Quant.batch).

    Key use cases:
    - Track expiry dates per lot (not just per product shelflife)
    - Trace which supplier delivered which lot
    - Support recalls: "find all stock from batch X"
    - FIFO picking: prefer oldest batches first
    """

    # Batch identifier (matches Quant.batch CharField)
    code = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_('Código do Lote'),
        help_text=_('Identificador único do lote. Usado como Quant.batch.'),
    )

    # Product reference (generic — works with any product model)
    product_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_('Tipo de Produto'),
    )
    product_id = models.PositiveIntegerField(verbose_name=_('ID do Produto'))
    product = GenericForeignKey('product_type', 'product_id')

    # Dates
    production_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('Data de Produção'),
    )
    expiry_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_('Data de Validade'),
        help_text=_('Último dia em que o lote pode ser vendido/utilizado'),
    )

    # Supplier / origin
    supplier = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name=_('Fornecedor'),
    )

    # Notes
    notes = models.TextField(
        blank=True,
        default='',
        verbose_name=_('Observações'),
    )

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Criado em'))

    objects = BatchQuerySet.as_manager()

    class Meta:
        verbose_name = _('Lote')
        verbose_name_plural = _('Lotes')
        ordering = ['expiry_date', 'production_date']
        indexes = [
            models.Index(fields=['product_type', 'product_id']),
            models.Index(fields=['expiry_date']),
        ]

    @property
    def is_expired(self) -> bool:
        """Is this batch past its expiry date?"""
        if self.expiry_date is None:
            return False
        from datetime import date
        return date.today() > self.expiry_date

    def __str__(self) -> str:
        expiry = f" (val:{self.expiry_date})" if self.expiry_date else ""
        return f"Lote {self.code}{expiry}"
