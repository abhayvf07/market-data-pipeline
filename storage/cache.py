"""
LRU Ticker Cache module.

Implements an OrderedDict-based Least Recently Used (LRU) cache
for recently fetched ticker data. Avoids redundant API calls during
retries or within a single pipeline session.

DSA demonstration: uses OrderedDict to maintain insertion/access order
and enforce capacity limits with O(1) eviction.
"""

import logging
from collections import OrderedDict
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class LRUTickerCache:
    """LRU cache for recently fetched stock data.

    Uses collections.OrderedDict to maintain access order and evict
    the least-recently-used entry when capacity is exceeded.
    All operations (get, put, evict) run in O(1) amortized time.

    Args:
        capacity: Maximum number of cache entries. Defaults to 32.

    Example:
        >>> cache = LRUTickerCache(capacity=3)
        >>> cache.put("AAPL", "6mo", df_aapl)
        >>> cache.put("MSFT", "6mo", df_msft)
        >>> result = cache.get("AAPL", "6mo")  # Moves AAPL to most-recent
        >>> cache.put("GOOGL", "6mo", df_googl)
        >>> cache.put("TSLA", "6mo", df_tsla)  # Evicts MSFT (least recent)
    """

    def __init__(self, capacity: int = 32):
        if capacity < 1:
            raise ValueError(f"Cache capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._store: OrderedDict[str, pd.DataFrame] = OrderedDict()
        logger.debug("LRUTickerCache initialized with capacity=%d", capacity)

    @staticmethod
    def _make_key(symbol: str, date_range: str) -> str:
        """Create a composite cache key from symbol and date range.

        Args:
            symbol: Stock ticker symbol (e.g. 'RELIANCE.NS').
            date_range: Fetch period string (e.g. '6mo').

        Returns:
            Composite key string.
        """
        return f"{symbol}:{date_range}"

    def get(self, symbol: str, date_range: str) -> Optional[pd.DataFrame]:
        """Retrieve cached DataFrame for a symbol/date_range pair.

        On a cache hit, the entry is moved to the most-recent position
        (LRU touch). Returns None on cache miss.

        Args:
            symbol: Stock ticker symbol.
            date_range: Fetch period string.

        Returns:
            Cached DataFrame or None if not found.
        """
        key = self._make_key(symbol, date_range)
        if key not in self._store:
            logger.debug("Cache MISS: %s", key)
            return None

        # Move to end (most recently used)
        self._store.move_to_end(key)
        logger.debug("Cache HIT: %s", key)
        return self._store[key]

    def put(self, symbol: str, date_range: str, df: pd.DataFrame) -> None:
        """Insert or update a cache entry.

        If the cache is at capacity, the least-recently-used entry
        is evicted via OrderedDict.popitem(last=False).

        Args:
            symbol: Stock ticker symbol.
            date_range: Fetch period string.
            df: OHLCV DataFrame to cache.
        """
        key = self._make_key(symbol, date_range)

        if key in self._store:
            # Update existing entry and move to end
            self._store.move_to_end(key)
            self._store[key] = df
            logger.debug("Cache UPDATE: %s", key)
            return

        # Evict oldest if at capacity
        if len(self._store) >= self._capacity:
            evicted_key, _ = self._store.popitem(last=False)
            logger.debug("Cache EVICT: %s (capacity=%d)", evicted_key, self._capacity)

        self._store[key] = df
        logger.debug("Cache PUT: %s (size=%d/%d)", key, len(self._store), self._capacity)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._store.clear()
        logger.debug("Cache cleared.")

    @property
    def capacity(self) -> int:
        """Maximum number of cache entries."""
        return self._capacity

    def __contains__(self, item: tuple[str, str]) -> bool:
        """Check if a (symbol, date_range) pair is in the cache.

        Args:
            item: Tuple of (symbol, date_range).

        Returns:
            True if the entry exists in the cache.
        """
        symbol, date_range = item
        return self._make_key(symbol, date_range) in self._store

    def __len__(self) -> int:
        """Number of entries currently in the cache."""
        return len(self._store)

    def __repr__(self) -> str:
        keys = list(self._store.keys())
        return (
            f"LRUTickerCache(capacity={self._capacity}, "
            f"size={len(self._store)}, "
            f"keys={keys})"
        )
