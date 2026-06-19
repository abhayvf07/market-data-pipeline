"""
Tests for the MetricsCalculator class.

Validates RSI computation, metric column generation, and
circuit-breaker anomaly detection against known inputs.
"""

import numpy as np
import pandas as pd
import pytest
from datetime import date, timedelta

from processing.transformer import MetricsCalculator


# --- Fixtures ---

@pytest.fixture
def sample_ohlcv():
    """Create a synthetic OHLCV DataFrame with 60 trading days."""
    np.random.seed(42)
    n = 60
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(n)]

    # Simulate a random walk for close prices starting at 100
    returns = np.random.normal(0.001, 0.02, n)
    close = 100 * np.cumprod(1 + returns)

    df = pd.DataFrame({
        "symbol": "TEST",
        "trade_date": dates,
        "open": close * (1 + np.random.uniform(-0.01, 0.01, n)),
        "high": close * (1 + np.random.uniform(0, 0.02, n)),
        "low": close * (1 - np.random.uniform(0, 0.02, n)),
        "close": close,
        "volume": np.random.randint(100000, 1000000, n),
    })
    return df


@pytest.fixture
def known_rsi_data():
    """Create a DataFrame with known prices for RSI hand-calculation.

    Uses the classic RSI example:
    14 periods of gains/losses with known RS = avg_gain / avg_loss.
    """
    # 15 closing prices (need 14 deltas for 14-period RSI)
    prices = [
        44.0, 44.34, 44.09, 43.61, 44.33,
        44.83, 45.10, 45.42, 45.84, 46.08,
        45.89, 46.03, 45.61, 46.28, 46.28,
    ]
    n = len(prices)
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(n)]

    return pd.DataFrame({
        "symbol": "RSI_TEST",
        "trade_date": dates,
        "open": prices,
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.5 for p in prices],
        "close": prices,
        "volume": [100000] * n,
    })


@pytest.fixture
def extreme_return_data():
    """Create a DataFrame with an extreme daily return (>20%)."""
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(5)]
    prices = [100, 102, 130, 125, 128]  # 130/102 - 1 ≈ 27.5% return

    return pd.DataFrame({
        "symbol": "EXTREME",
        "trade_date": dates,
        "open": prices,
        "high": [p + 2 for p in prices],
        "low": [p - 2 for p in prices],
        "close": prices,
        "volume": [500000] * 5,
    })


# --- Tests ---

class TestMetricsCalculator:
    """Test suite for MetricsCalculator."""

    def test_init_validates_columns(self):
        """Should raise ValueError if required columns are missing."""
        bad_df = pd.DataFrame({"symbol": ["A"], "close": [100]})
        with pytest.raises(ValueError, match="Missing required columns"):
            MetricsCalculator(bad_df)

    def test_compute_adds_all_columns(self, sample_ohlcv):
        """Should add all expected metric columns."""
        calc = MetricsCalculator(sample_ohlcv)
        result = calc.compute()

        expected_cols = {"daily_return", "sma_20", "sma_50", "volatility_20d", "rsi_14"}
        assert expected_cols.issubset(set(result.columns)), (
            f"Missing columns: {expected_cols - set(result.columns)}"
        )

    def test_compute_preserves_row_count(self, sample_ohlcv):
        """Should not add or remove rows during computation."""
        calc = MetricsCalculator(sample_ohlcv)
        result = calc.compute()
        assert len(result) == len(sample_ohlcv)

    def test_daily_return_first_is_nan(self, sample_ohlcv):
        """First daily return should be NaN (no previous close)."""
        calc = MetricsCalculator(sample_ohlcv)
        result = calc.compute()
        assert pd.isna(result["daily_return"].iloc[0])

    def test_daily_return_calculation(self, sample_ohlcv):
        """Daily return should equal pct_change of close prices."""
        calc = MetricsCalculator(sample_ohlcv)
        result = calc.compute()

        # Manual calculation for row 1
        expected = (sample_ohlcv["close"].iloc[1] / sample_ohlcv["close"].iloc[0]) - 1
        actual = result["daily_return"].iloc[1]
        assert abs(actual - expected) < 1e-10

    def test_sma_20_at_row_20(self, sample_ohlcv):
        """SMA-20 at row 20 should equal mean of first 20 close prices."""
        calc = MetricsCalculator(sample_ohlcv)
        result = calc.compute()

        # With min_periods=1, SMA at row 19 (0-indexed) = mean of rows 0..19
        expected = sample_ohlcv["close"].iloc[:20].mean()
        actual = result["sma_20"].iloc[19]
        assert abs(actual - expected) < 1e-8

    def test_volatility_is_annualized(self, sample_ohlcv):
        """Volatility should be annualized (multiplied by √252)."""
        calc = MetricsCalculator(sample_ohlcv)
        result = calc.compute()

        # Non-annualized 20-day rolling std of returns
        raw_std = result["daily_return"].rolling(20, min_periods=1).std()

        # Check that volatility ≈ raw_std × √252 (for post-warmup rows)
        idx = 30  # Well past warmup period
        expected = raw_std.iloc[idx] * np.sqrt(252)
        actual = result["volatility_20d"].iloc[idx]
        assert abs(actual - expected) < 1e-8


class TestRSI:
    """Test suite for RSI calculation."""

    def test_rsi_range(self, sample_ohlcv):
        """RSI values should be between 0 and 100 (where computed)."""
        calc = MetricsCalculator(sample_ohlcv)
        result = calc.compute()
        rsi_valid = result["rsi_14"].dropna()
        assert (rsi_valid >= 0).all() and (rsi_valid <= 100).all()

    def test_rsi_known_values(self, known_rsi_data):
        """RSI with known inputs should match hand-calculated value.

        Using classic Wilder RSI example:
        14-period gains and losses from the known_rsi_data fixture.
        """
        calc = MetricsCalculator(known_rsi_data)
        result = calc.compute()

        # The RSI at the last row (index 14) should be calculable
        rsi_last = result["rsi_14"].iloc[-1]

        # Hand-calculation from the known prices:
        # Deltas: [0.34, -0.25, -0.48, 0.72, 0.50, 0.27, 0.32, 0.42, 0.24,
        #          -0.19, 0.14, -0.42, 0.67, 0.00]
        # Gains: [0.34, 0, 0, 0.72, 0.50, 0.27, 0.32, 0.42, 0.24, 0, 0.14, 0, 0.67, 0]
        # Losses: [0, 0.25, 0.48, 0, 0, 0, 0, 0, 0, 0.19, 0, 0.42, 0, 0]
        # avg_gain = sum(gains)/14 = 3.62/14 ≈ 0.2586
        # avg_loss = sum(losses)/14 = 1.34/14 ≈ 0.0957
        # RS = 0.2586 / 0.0957 ≈ 2.7023
        # RSI = 100 - 100/(1+2.7023) ≈ 73.0
        assert rsi_last is not None and not pd.isna(rsi_last)
        assert 65 < rsi_last < 80, f"Expected RSI ~73, got {rsi_last:.2f}"


class TestValidation:
    """Test suite for data validation."""

    def test_validate_catches_extreme_returns(self, extreme_return_data):
        """Should flag daily returns exceeding the 20% threshold."""
        calc = MetricsCalculator(extreme_return_data)
        calc.compute()
        warnings = calc.validate()

        # Should catch the ~27.5% return
        extreme_warnings = [w for w in warnings if "Extreme return" in w]
        assert len(extreme_warnings) > 0, "Should have flagged the extreme return"

    def test_validate_passes_normal_data(self, sample_ohlcv):
        """Normal data should produce no extreme-return warnings."""
        calc = MetricsCalculator(sample_ohlcv)
        calc.compute()
        warnings = calc.validate()

        extreme_warnings = [w for w in warnings if "Extreme return" in w]
        # With seed=42, random walk unlikely to hit 20% in one day
        assert len(extreme_warnings) == 0, f"Unexpected warnings: {extreme_warnings}"

    def test_validate_flags_null_close(self):
        """Should warn about missing close prices."""
        dates = [date(2024, 1, i + 1) for i in range(5)]
        df = pd.DataFrame({
            "symbol": "NULL_TEST",
            "trade_date": dates,
            "open": [100, 101, None, 103, 104],
            "high": [102, 103, None, 105, 106],
            "low": [98, 99, None, 101, 102],
            "close": [101, None, 102, 104, 105],
            "volume": [10000] * 5,
        })
        calc = MetricsCalculator(df)
        calc.compute()
        warnings = calc.validate()

        null_warnings = [w for w in warnings if "missing close" in w]
        assert len(null_warnings) > 0


class TestMetricsProperty:
    """Test the lazy metrics_df property."""

    def test_metrics_df_lazy_computation(self, sample_ohlcv):
        """metrics_df should trigger computation on first access."""
        calc = MetricsCalculator(sample_ohlcv)
        assert not calc._metrics_computed

        _ = calc.metrics_df
        assert calc._metrics_computed

    def test_repr(self, sample_ohlcv):
        """__repr__ should include symbol and status."""
        calc = MetricsCalculator(sample_ohlcv)
        r = repr(calc)
        assert "TEST" in r
        assert "pending" in r

        calc.compute()
        r = repr(calc)
        assert "computed" in r
