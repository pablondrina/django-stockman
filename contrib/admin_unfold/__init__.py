"""Stockman Admin with Unfold theme."""

# Lazy imports to avoid circular dependencies
# Import directly from shopman_commons when needed:
#   from shopman_commons.contrib.admin_unfold.base import BaseModelAdmin

__all__ = [
    "BaseModelAdmin",
    "BaseTabularInline",
    "format_quantity",
]


def __getattr__(name):
    """Lazy import to avoid circular imports during app loading."""
    if name in ("BaseModelAdmin", "BaseTabularInline"):
        from shopman_commons.contrib.admin_unfold.base import (
            BaseModelAdmin,
            BaseTabularInline,
        )
        return locals()[name]
    if name == "format_quantity":
        from shopman_commons.formatting import format_quantity
        return format_quantity
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
