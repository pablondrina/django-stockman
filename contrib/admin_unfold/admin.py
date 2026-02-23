"""
Stockman Admin with Unfold theme.

This module provides Unfold-styled admin classes for Stockman models.
To use, add 'stockman.contrib.admin_unfold' to INSTALLED_APPS after 'stockman'.

The admins will automatically register the Unfold versions.
"""

import logging

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.decorators import display

logger = logging.getLogger(__name__)

from shopman_commons.contrib.admin_unfold.badges import unfold_badge, unfold_badge_numeric
from shopman_commons.contrib.admin_unfold.base import BaseModelAdmin
from shopman_commons.formatting import format_quantity
from stockman.models import Batch, Position, Quant, Move, Hold, HoldStatus, StockAlert


# =============================================================================
# HELPERS
# =============================================================================


def _format_datetime(dt):
    """Format datetime as DD/MM/AA . HH:MM."""
    if dt:
        return dt.strftime('%d/%m/%y · %H:%M')
    return '-'


def _format_date(d):
    """Format date as DD/MM/AA."""
    if d:
        return d.strftime('%d/%m/%y')
    return '-'


# =============================================================================
# POSITION ADMIN
# =============================================================================


@admin.register(Position)
class PositionAdmin(BaseModelAdmin):
    """Admin for Position model."""

    list_display = ['code', 'name', 'kind', 'is_saleable']
    list_filter = ['kind', 'is_saleable']
    search_fields = ['code', 'name']
    readonly_fields = ['created_at', 'updated_at']

    # Unfold options
    compressed_fields = True
    warn_unsaved_form = True


# =============================================================================
# SALDO (QUANT) ADMIN
# =============================================================================


@admin.register(Quant)
class QuantAdmin(BaseModelAdmin):
    """Admin for Saldo/Quant model (read-only).

    Saldos should only be modified via stock.add(), stock.remove() etc.
    to maintain audit trail via Movimentação records.
    """

    list_display = ['product_display', 'position', 'target_date_display', 'quantity_display', 'held_display', 'available_display']
    list_filter = ['position', 'target_date']
    search_fields = ['object_id']
    readonly_fields = ['content_type', 'object_id', 'position', 'target_date', '_quantity', 'created_at', 'updated_at']
    date_hierarchy = 'target_date'
    ordering = ['-target_date', 'position']

    # Unfold options
    compressed_fields = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @display(description=_('Produto'))
    def product_display(self, obj):
        return str(obj.product) if obj.product else '?'

    @display(description=_('Data'))
    def target_date_display(self, obj):
        """Display target_date in DD/MM/AA format."""
        return _format_date(obj.target_date)

    @display(description=_('Quantidade'))
    def quantity_display(self, obj):
        return format_quantity(obj.quantity)

    @display(description=_('Reservado'))
    def held_display(self, obj):
        """Display reserved quantity with Unfold badge."""
        held = obj.held
        formatted = format_quantity(held)
        if held > 0:
            return unfold_badge_numeric(formatted, 'yellow')
        else:
            return unfold_badge_numeric(formatted, 'base')

    @display(description=_('Disponivel'))
    def available_display(self, obj):
        """Display available quantity with Unfold badge."""
        available = obj.available
        formatted = format_quantity(available)
        if available > 0:
            return unfold_badge_numeric(formatted, 'green')
        elif available == 0:
            return unfold_badge_numeric(formatted, 'base')
        else:
            return unfold_badge_numeric(formatted, 'red')


# =============================================================================
# MOVIMENTAÇÃO (MOVE) ADMIN
# =============================================================================


@admin.register(Move)
class MoveAdmin(BaseModelAdmin):
    """Admin for Movimentação/Move model (read-only)."""

    list_display = ['timestamp_display', 'quant_display', 'delta_display', 'reason', 'user']
    list_filter = ['timestamp', 'user']
    search_fields = ['reason']
    readonly_fields = ['quant', 'delta', 'reference_type', 'reference_id', 'reason', 'metadata', 'timestamp', 'user']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # Unfold options
    compressed_fields = True

    @display(description=_('Data e Hora'))
    def timestamp_display(self, obj):
        """Display timestamp in DD/MM/AA . HH:MM format."""
        return _format_datetime(obj.timestamp)

    @display(description=_('Saldo'))
    def quant_display(self, obj):
        return str(obj.quant.product) if obj.quant and obj.quant.product else '?'

    @display(description=_('Variacao'))
    def delta_display(self, obj):
        """Display delta with Unfold badge."""
        formatted = format_quantity(abs(obj.delta))
        if obj.delta > 0:
            return unfold_badge_numeric(f'+{formatted}', 'green')
        else:
            return unfold_badge_numeric(f'-{formatted}', 'red')


# =============================================================================
# RESERVA (HOLD) ADMIN
# =============================================================================


@admin.register(Hold)
class HoldAdmin(BaseModelAdmin):
    """Admin for Reserva/Hold model (read-only).

    Reservas should only be created via stock.reserve() and released via stock.release()
    to maintain proper inventory accounting. Admin actions allow releasing holds.
    """

    list_display = ['id', 'product_display', 'quantity', 'target_date_display', 'status_display', 'is_demand_display', 'expires_at_display']
    list_filter = ['status', 'target_date']
    search_fields = ['object_id']
    readonly_fields = ['hold_id', 'content_type', 'object_id', 'quant', 'target_date', 'quantity', 'status', 'is_demand', 'expires_at', 'purpose_type', 'purpose_id', 'metadata', 'created_at', 'resolved_at']
    actions = ['release_holds']

    # Unfold options
    compressed_fields = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @display(description=_('Produto'))
    def product_display(self, obj):
        return str(obj.product) if obj.product else '?'

    @display(description=_('Status'))
    def status_display(self, obj):
        """Display status with Unfold badge."""
        status_map = {
            HoldStatus.PENDING: ('PENDENTE', 'base'),
            HoldStatus.CONFIRMED: ('CONFIRMADO', 'blue'),
            HoldStatus.FULFILLED: ('ATENDIDO', 'green'),
            HoldStatus.RELEASED: ('LIBERADO', 'base'),
        }
        label, color = status_map.get(obj.status, (obj.get_status_display().upper(), 'base'))
        return unfold_badge(label, color)

    @display(description=_('Data'))
    def target_date_display(self, obj):
        """Display target_date in DD/MM/AA format."""
        return _format_date(obj.target_date)

    @display(description=_('Expira em'))
    def expires_at_display(self, obj):
        """Display expires_at in DD/MM/AA . HH:MM format."""
        return _format_datetime(obj.expires_at)

    @display(description=_('Demanda?'), boolean=True)
    def is_demand_display(self, obj):
        return obj.is_demand

    @admin.action(description=_('Liberar holds selecionados'))
    def release_holds(self, request, queryset):
        from stockman import stock

        count = 0
        for hold in queryset.filter(status__in=[HoldStatus.PENDING, HoldStatus.CONFIRMED]):
            try:
                stock.release(hold.hold_id, reason='Liberado via admin')
                count += 1
            except (ValueError, LookupError) as exc:
                logger.warning("release_holds: failed to release %s: %s", hold.hold_id, exc)

        self.message_user(request, _('{count} hold(s) liberado(s).').format(count=count))


# =============================================================================
# STOCK ALERT ADMIN
# =============================================================================


@admin.register(StockAlert)
class StockAlertAdmin(BaseModelAdmin):
    """Admin for StockAlert model."""

    list_display = ['__str__', 'min_quantity', 'position', 'is_active_display', 'last_triggered_at_display']
    list_filter = ['is_active', 'position']
    search_fields = ['object_id']
    readonly_fields = ['last_triggered_at', 'created_at', 'updated_at']

    compressed_fields = True
    warn_unsaved_form = True

    @display(description=_('Ativo'))
    def is_active_display(self, obj):
        if obj.is_active:
            return unfold_badge('ATIVO', 'green')
        return unfold_badge('INATIVO', 'base')

    @display(description=_('Último Disparo'))
    def last_triggered_at_display(self, obj):
        return _format_datetime(obj.last_triggered_at)


# =============================================================================
# BATCH (LOT) ADMIN
# =============================================================================


@admin.register(Batch)
class BatchAdmin(BaseModelAdmin):
    """Admin for Batch/Lot model."""

    list_display = ['code', 'product_display', 'production_date_display',
                    'expiry_date_display', 'supplier', 'is_expired_display']
    list_filter = ['expiry_date', 'production_date']
    search_fields = ['code', 'supplier']
    readonly_fields = ['created_at']

    compressed_fields = True
    warn_unsaved_form = True

    @display(description=_('Produto'))
    def product_display(self, obj):
        return str(obj.product) if obj.product else '?'

    @display(description=_('Produção'))
    def production_date_display(self, obj):
        return _format_date(obj.production_date)

    @display(description=_('Validade'))
    def expiry_date_display(self, obj):
        return _format_date(obj.expiry_date)

    @display(description=_('Expirado'))
    def is_expired_display(self, obj):
        if obj.is_expired:
            return unfold_badge('EXPIRADO', 'red')
        return unfold_badge('VÁLIDO', 'green')
