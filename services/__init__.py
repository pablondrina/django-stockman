"""
Stock services — modular organization of stock operations.

Re-exports all public methods so existing code keeps working:
    from stockman.services import StockQueries, StockMovements, StockHolds, StockPlanning
"""

from stockman.services.holds import StockHolds
from stockman.services.movements import StockMovements
from stockman.services.planning import StockPlanning
from stockman.services.queries import StockQueries

__all__ = [
    'StockQueries',
    'StockMovements',
    'StockHolds',
    'StockPlanning',
]
