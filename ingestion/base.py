"""
Base data source module.

Defines the abstract base class for all market data sources.
Subclasses must implement fetch() to return normalized OHLCV data.
This enables polymorphic data source swapping without changing
downstream pipeline code.
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseDataSource(ABC):
    """Abstract base class for market data sources.

    All data sources must produce a DataFrame with columns:
    [symbol, trade_date, open, high, low, close, volume]

    This inheritance hierarchy demonstrates polymorphism: the pipeline
    orchestrator accepts any BaseDataSource subclass, so swapping
    data sources requires zero changes to downstream code.

    Args:
        symbol: Stock ticker symbol (e.g. 'RELIANCE.NS').
        period: Lookback period (e.g. '6mo', '1y').
        interval: Data interval (e.g. '1d', '1h').
    """

    # Required output columns (enforced by validate_output)
    REQUIRED_COLUMNS = ["symbol", "trade_date", "open", "high", "low", "close", "volume"]

    def __init__(self, symbol: str, period: str = "6mo", interval: str = "1d"):
        self.symbol = symbol.upper()
        self.period = period
        self.interval = interval

    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        """Fetch OHLCV data from the data source.

        Returns:
            DataFrame with columns: [symbol, trade_date, open, high, low, close, volume]

        Raises:
            ValueError: If no data is returned.
            ConnectionError: If the API call fails after retries.
        """
        ...

    @property
    def source_name(self) -> str:
        """Human-readable name of this data source."""
        return self.__class__.__name__

    def validate_output(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate that fetch output has the required schema.

        Args:
            df: Raw DataFrame from fetch().

        Returns:
            Validated DataFrame.

        Raises:
            ValueError: If required columns are missing or DataFrame is empty.
        """
        if df.empty:
            raise ValueError(
                f"{self.source_name}: No data returned for {self.symbol}"
            )

        missing = set(self.REQUIRED_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(
                f"{self.source_name}: Missing columns {missing} for {self.symbol}"
            )

        return df[self.REQUIRED_COLUMNS]

    def __repr__(self) -> str:
        return (
            f"{self.source_name}("
            f"symbol={self.symbol!r}, "
            f"period={self.period!r}, "
            f"interval={self.interval!r})"
        )
