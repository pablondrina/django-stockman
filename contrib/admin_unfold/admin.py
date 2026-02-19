"""
Stockman Admin with Unfold theme.

This module provides Unfold-styled admin classes for Stockman models.
To use, add 'stockman.contrib.admin_unfold' to INSTALLED_APPS after 'stockman'.

The admins will automatically register the Unfold versions.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.decorators import display

from stockman.contrib.admin_unfold.base import BaseModelAdmin, format_quantity
from stockman.models import Position, Quant, Move, Hold, HoldStatus


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


def _unfold_badge_numeric(text, color='base'):
    """
    Create Unfold badge for numeric values (normal font size, no uppercase).

    Colors: 'base' (gray), 'red', 'green', 'yellow', 'blue'
    """
    base_classes = "inline-block font-semibold h-6 leading-6 px-2 rounded-default whitespace-nowrap"

    color_classes = {
        'base': 'bg-base-100 text-base-700 dark:bg-base-500/20 dark:text-base-200',
        'red': 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400',
        'green': 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400',
        'yellow': 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400',
        'blue': 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400',
    }

    classes = f"{base_classes} {color_classes.get(color, color_classes['base'])}"
    return format_html('<span class="{}">{}</span>', classes, text)


def _unfold_badge_text(text, color='base'):
    """
    Create Unfold badge for alphanumeric text (smaller font, uppercase).

    Colors: 'base' (gray), 'red', 'green', 'yellow', 'blue'
    """
    base_classes = "inline-block font-semibold h-6 leading-6 px-2 rounded-default text-[11px] uppercase whitespace-nowrap"

    color_classes = {
        'base': 'bg-base-100 text-base-700 dark:bg-base-500/20 dark:text-base-200',
        'red': 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400',
        'green': 'bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400',
        'yellow': 'bg-yellow-100 text-yellow-700 dark:bg-yellow-500/20 dark:text-yellow-400',
        'blue': 'bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400',
    }

    classes = f"{base_classes} {color_classes.get(color, color_classes['base'])}"
    return format_html('<span class="{}">{}</span>', classes, text)


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
# QUANT ADMIN
# =============================================================================


@admin.register(Quant)
class QuantAdmin(BaseModelAdmin):
    """Admin for Quant model (read-only).

    Quants should only be modified via stock.add(), stock.remove() etc.
    to maintain audit trail via Move records.
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
            return _unfold_badge_numeric(formatted, 'yellow')
        else:
            return _unfold_badge_numeric(formatted, 'base')

    @display(description=_('Disponivel'))
    def available_display(self, obj):
        """Display available quantity with Unfold badge."""
        available = obj.available
        formatted = format_quantity(available)
        if available > 0:
            return _unfold_badge_numeric(formatted, 'green')
        elif available == 0:
            return _unfold_badge_numeric(formatted, 'base')
        else:
            return _unfold_badge_numeric(formatted, 'red')


# =============================================================================
# MOVE ADMIN
# =============================================================================


@admin.register(Move)
class MoveAdmin(BaseModelAdmin):
    """Admin for Move model (read-only)."""

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

    @display(description=_('Item'))
    def quant_display(self, obj):
        return str(obj.quant.product) if obj.quant and obj.quant.product else '?'

    @display(description=_('Variacao'))
    def delta_display(self, obj):
        """Display delta with Unfold badge."""
        formatted = format_quantity(abs(obj.delta))
        if obj.delta > 0:
            return _unfold_badge_numeric(f'+{formatted}', 'green')
        else:
            return _unfold_badge_numeric(f'-{formatted}', 'red')


# =============================================================================
# HOLD ADMIN
# =============================================================================


@admin.register(Hold)
class HoldAdmin(BaseModelAdmin):
    """Admin for Hold model (read-only).

    Holds should only be created via stock.reserve() and released via stock.release()
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
        return _unfold_badge_text(label, color)

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
            except Exception:
                pass

        self.message_user(request, _('{count} hold(s) liberado(s).').format(count=count))
