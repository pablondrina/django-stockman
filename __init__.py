"""
Django Stockman — Motor Unificado de Estoque.

O parceiro de dança perfeito para o Django Salesman.

Uso:
    from stockman import stock, StockError
    
    stock.plan(50, croissant, sexta)
    stock.hold(5, croissant, sexta)
    stock.available(croissant, sexta)  # 45
"""


def __getattr__(name):
    """Lazy import to avoid circular imports during app loading."""
    if name == 'stock':
        from stockman.service import Stock
        return Stock
    elif name == 'StockError':
        from stockman.exceptions import StockError
        return StockError
    elif name == 'Position':
        from stockman.models.position import Position
        return Position
    elif name == 'Quant':
        from stockman.models.quant import Quant
        return Quant
    elif name == 'Move':
        from stockman.models.move import Move
        return Move
    elif name == 'Hold':
        from stockman.models.hold import Hold
        return Hold
    elif name == 'PositionKind':
        from stockman.models.enums import PositionKind
        return PositionKind
    elif name == 'HoldStatus':
        from stockman.models.enums import HoldStatus
        return HoldStatus
    elif name == 'StockAlert':
        from stockman.models.alert import StockAlert
        return StockAlert
    elif name == 'Batch':
        from stockman.models.batch import Batch
        return Batch
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'stock',
    'StockError',
    'Position',
    'Quant',
    'Move',
    'Hold',
    'PositionKind',
    'HoldStatus',
    'StockAlert',
    'Batch',
]

__version__ = '0.2.0'
