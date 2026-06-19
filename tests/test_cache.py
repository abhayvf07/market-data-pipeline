"""
Tests for the LRUTickerCache class.

Validates OrderedDict-based LRU eviction, capacity enforcement,
cache hit/miss behavior, and special methods (__contains__, __len__).
"""

import pandas as pd
import pytest
from datetime import date, timedelta

from storage.cache import LRUTickerCache


# --- Fixtures ---

@pytest.fixture
def small_cache():
    """Create a cache with capacity 3 for testing eviction."""
    return LRUTickerCache(capacity=3)


@pytest.fixture
def sample_df():
    """Create a minimal DataFrame for cache testing."""
    return pd.DataFrame({
        "symbol": ["TEST"],
        "trade_date": [date(2024, 1, 1)],
        "close": [100.0],
    })


def make_df(symbol: str, n: int = 5) -> pd.DataFrame:
    """Helper to create a labeled DataFrame."""
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({
        "symbol": [symbol] * n,
        "trade_date": dates,
        "close": [100 + i for i in range(n)],
    })


# --- Tests ---

class TestLRUTickerCacheBasics:
    """Test basic cache operations."""

    def test_init_default_capacity(self):
        """Default capacity should be 32."""
        cache = LRUTickerCache()
        assert cache.capacity == 32
        assert len(cache) == 0

    def test_init_custom_capacity(self):
        """Should accept custom capacity."""
        cache = LRUTickerCache(capacity=10)
        assert cache.capacity == 10

    def test_init_rejects_zero_capacity(self):
        """Should raise ValueError for capacity < 1."""
        with pytest.raises(ValueError, match="capacity must be >= 1"):
            LRUTickerCache(capacity=0)

    def test_put_and_get(self, small_cache, sample_df):
        """Put then get should return the same DataFrame."""
        small_cache.put("AAPL", "6mo", sample_df)
        result = small_cache.get("AAPL", "6mo")

        assert result is not None
        assert len(result) == len(sample_df)
        pd.testing.assert_frame_equal(result, sample_df)

    def test_get_miss_returns_none(self, small_cache):
        """Cache miss should return None."""
        result = small_cache.get("NONEXISTENT", "6mo")
        assert result is None

    def test_len_tracks_entries(self, small_cache):
        """__len__ should reflect the number of cached entries."""
        assert len(small_cache) == 0

        small_cache.put("A", "6mo", make_df("A"))
        assert len(small_cache) == 1

        small_cache.put("B", "6mo", make_df("B"))
        assert len(small_cache) == 2

    def test_contains(self, small_cache):
        """__contains__ should check for (symbol, period) pairs."""
        small_cache.put("AAPL", "6mo", make_df("AAPL"))

        assert ("AAPL", "6mo") in small_cache
        assert ("AAPL", "1y") not in small_cache
        assert ("MSFT", "6mo") not in small_cache


class TestLRUEviction:
    """Test LRU eviction behavior — core DSA demonstration."""

    def test_eviction_at_capacity(self, small_cache):
        """When full, oldest entry should be evicted on new insert.

        OrderedDict.popitem(last=False) removes the first-inserted
        (least-recently-used) entry in O(1) time.
        """
        small_cache.put("A", "6mo", make_df("A"))
        small_cache.put("B", "6mo", make_df("B"))
        small_cache.put("C", "6mo", make_df("C"))
        assert len(small_cache) == 3

        # Adding D should evict A (oldest)
        small_cache.put("D", "6mo", make_df("D"))
        assert len(small_cache) == 3  # Still at capacity

        assert small_cache.get("A", "6mo") is None  # Evicted
        assert small_cache.get("D", "6mo") is not None  # Present

    def test_access_refreshes_lru_order(self, small_cache):
        """Accessing an entry should move it to most-recent (not evicted next).

        This is the key LRU behavior: move_to_end() on access.
        """
        small_cache.put("A", "6mo", make_df("A"))
        small_cache.put("B", "6mo", make_df("B"))
        small_cache.put("C", "6mo", make_df("C"))

        # Access A — moves it to most-recent
        small_cache.get("A", "6mo")

        # Add D — should evict B (now the oldest), not A
        small_cache.put("D", "6mo", make_df("D"))

        assert small_cache.get("A", "6mo") is not None  # Refreshed, still present
        assert small_cache.get("B", "6mo") is None  # Evicted (was oldest after A's refresh)
        assert small_cache.get("C", "6mo") is not None
        assert small_cache.get("D", "6mo") is not None

    def test_update_existing_entry(self, small_cache):
        """Putting an existing key should update it and refresh LRU order."""
        small_cache.put("A", "6mo", make_df("A", n=3))
        small_cache.put("B", "6mo", make_df("B"))
        small_cache.put("C", "6mo", make_df("C"))

        # Update A with new data
        new_df = make_df("A", n=10)
        small_cache.put("A", "6mo", new_df)

        assert len(small_cache) == 3  # No extra entry
        result = small_cache.get("A", "6mo")
        assert len(result) == 10  # Updated data

    def test_eviction_order_fifo_without_access(self, small_cache):
        """Without any access, eviction should follow insertion order (FIFO)."""
        small_cache.put("A", "6mo", make_df("A"))
        small_cache.put("B", "6mo", make_df("B"))
        small_cache.put("C", "6mo", make_df("C"))

        small_cache.put("D", "6mo", make_df("D"))  # Evicts A
        small_cache.put("E", "6mo", make_df("E"))  # Evicts B
        small_cache.put("F", "6mo", make_df("F"))  # Evicts C

        assert small_cache.get("A", "6mo") is None
        assert small_cache.get("B", "6mo") is None
        assert small_cache.get("C", "6mo") is None
        assert small_cache.get("D", "6mo") is not None
        assert small_cache.get("E", "6mo") is not None
        assert small_cache.get("F", "6mo") is not None


class TestCacheClear:
    """Test cache clear operation."""

    def test_clear_empties_cache(self, small_cache):
        """Clear should remove all entries."""
        small_cache.put("A", "6mo", make_df("A"))
        small_cache.put("B", "6mo", make_df("B"))
        assert len(small_cache) == 2

        small_cache.clear()
        assert len(small_cache) == 0
        assert small_cache.get("A", "6mo") is None


class TestCacheRepr:
    """Test __repr__ output."""

    def test_repr_shows_capacity_and_size(self, small_cache):
        """repr should include capacity and current size."""
        r = repr(small_cache)
        assert "capacity=3" in r
        assert "size=0" in r

    def test_repr_shows_keys(self, small_cache):
        """repr should list cached keys."""
        small_cache.put("AAPL", "6mo", make_df("AAPL"))
        r = repr(small_cache)
        assert "AAPL:6mo" in r
