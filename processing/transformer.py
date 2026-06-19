"""
Financial metrics transformer module.

Provides the MetricsCalculator class for computing derived financial
indicators from raw OHLCV data: daily returns, moving averages,
annualized volatility, and RSI.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """Computes financial metrics from raw OHLCV price data.

    Computes: daily returns, SMA-20, SMA-50, 20-day annualized
    volatility, and 14-period RSI. Includes data validation for
    circuit-breaker-level anomalies.

    Args:
        df: DataFrame with at least [symbol, trade_date, close] columns.

    Example:
        >>> calc = MetricsCalculator(raw_df)
        >>> enriched = calc.compute()
        >>> warnings = calc.validate()
    """

    # Annualization factor: √252 trading days per year
    ANNUALIZATION_FACTOR = np.sqrt(252)

    # Threshold for flagging extreme daily returns (20% = circuit breaker)
    EXTREME_RETURN_THRESHOLD = 0.20

    def __init__(self, df: pd.DataFrame):
        required_cols = {"symbol", "trade_date", "open", "high", "low", "close", "volume"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        self._df = df.copy()
        self._df = self._df.sort_values("trade_date").reset_index(drop=True)
        self._metrics_computed = False
        self._symbol = self._df["symbol"].iloc[0] if len(self._df) > 0 else "UNKNOWN"

        logger.debug(
            "MetricsCalculator initialized for %s (%d rows)",
            self._symbol, len(self._df),
        )

    def compute(self) -> pd.DataFrame:
        """Compute all derived financial metrics.

        Adds columns: daily_return, sma_20, sma_50, volatility_20d, rsi_14.

        Returns:
            DataFrame enriched with all computed metrics.
        """
        logger.info("Computing metrics for %s (%d rows)", self._symbol, len(self._df))

        # Daily returns via percentage change
        self._df["daily_return"] = self._df["close"].pct_change()

        # Simple Moving Averages
        self._df["sma_20"] = self._df["close"].rolling(window=20, min_periods=1).mean()
        self._df["sma_50"] = self._df["close"].rolling(window=50, min_periods=1).mean()

        # Annualized 20-day rolling volatility
        # Multiply by √252 to annualize daily standard deviation
        self._df["volatility_20d"] = (
            self._df["daily_return"]
            .rolling(window=20, min_periods=1)
            .std()
            * self.ANNUALIZATION_FACTOR
        )

        # Relative Strength Index (14-period)
        self._df["rsi_14"] = self._compute_rsi(self._df["close"], period=14)

        self._metrics_computed = True

        logger.info(
            "Metrics computed for %s: SMA-20/50, volatility, RSI-14",
            self._symbol,
        )

        return self._df

    def validate(self) -> list[str]:
        """Run sanity checks on the computed data.

        Checks for:
        - Extreme daily returns (beyond circuit-breaker threshold)
        - Missing/null closing prices
        - NaN values in critical computed columns

        Returns:
            List of warning messages. Empty list means all checks passed.
        """
        warnings = []

        # Check for missing close prices
        null_close = self._df["close"].isna().sum()
        if null_close > 0:
            msg = f"{self._symbol}: {null_close} missing close price(s)"
            warnings.append(msg)
            logger.warning(msg)

        # Check for extreme daily returns (circuit-breaker-level moves)
        if "daily_return" in self._df.columns:
            extreme = self._df[
                self._df["daily_return"].abs() > self.EXTREME_RETURN_THRESHOLD
            ]
            for _, row in extreme.iterrows():
                msg = (
                    f"{self._symbol}: Extreme return {row['daily_return']:.4f} "
                    f"({row['daily_return'] * 100:.2f}%) on {row['trade_date']}"
                )
                warnings.append(msg)
                logger.warning(msg)

        # Check for unexpected NaNs in computed columns (beyond warm-up period)
        if self._metrics_computed:
            warmup = 50  # Max lookback window
            if len(self._df) > warmup:
                post_warmup = self._df.iloc[warmup:]
                for col in ["sma_20", "sma_50", "volatility_20d", "rsi_14"]:
                    if col in post_warmup.columns:
                        nan_count = post_warmup[col].isna().sum()
                        if nan_count > 0:
                            msg = (
                                f"{self._symbol}: {nan_count} NaN values in "
                                f"{col} after warm-up period"
                            )
                            warnings.append(msg)
                            logger.warning(msg)

        if not warnings:
            logger.info("%s: All validation checks passed.", self._symbol)

        return warnings

    @property
    def metrics_df(self) -> pd.DataFrame:
        """Lazily compute and return the enriched DataFrame.

        Computes metrics on first access if not already computed.
        """
        if not self._metrics_computed:
            self.compute()
        return self._df

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Compute Relative Strength Index (Wilder's method).

        RSI measures the speed and magnitude of price changes to
        evaluate overbought (>70) or oversold (<30) conditions.

        Args:
            close: Series of closing prices.
            period: RSI lookback period (default 14).

        Returns:
            Series of RSI values (0-100 scale).
        """
        delta = close.diff()

        # Separate gains and losses
        gain = delta.clip(lower=0)
        loss = (-delta.clip(upper=0))

        # Use rolling mean for initial RSI calculation (SMA-based)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        # Relative Strength
        rs = avg_gain / avg_loss

        # RSI formula: 100 - (100 / (1 + RS))
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def __repr__(self) -> str:
        status = "computed" if self._metrics_computed else "pending"
        date_range = ""
        if len(self._df) > 0:
            date_range = (
                f", dates={self._df['trade_date'].min()} "
                f"to {self._df['trade_date'].max()}"
            )
        return (
            f"MetricsCalculator("
            f"symbol={self._symbol!r}, "
            f"rows={len(self._df)}, "
            f"status={status}"
            f"{date_range})"
        )
