"""Background data collector for PolySuite.

Runs insider, convergence, contrarian scans and caches results
so dashboard buttons return data immediately.
"""

from src.collector.runner import MarketDataCollector

__all__ = ["MarketDataCollector"]
