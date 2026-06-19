"""
Alpha Vantage data source module.

Implements the AlphaVantageSource class as a documented fallback
data source. Demonstrates inheritance from BaseDataSource and
provides a real implementation that can be activated with an API key.

This fallback is useful when yfinance is rate-limited or unavailable.
Free API keys are available at https://www.alphavantage.co/support/#api-key
"""

import logging
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from ingestion.base import BaseDataSource

logger = logging.getLogger(__name__)


class AlphaVantageSource(BaseDataSource):
    """Fetches OHLCV data from Alpha Vantage API.

    Serves as a documented fallback when yfinance is rate-limited.
    Inherits from BaseDataSource, demonstrating polymorphism —
    can be swapped in wherever YFinanceSource is used with zero
    changes to downstream pipeline code.

    Args:
        symbol: Stock ticker symbol (e.g. 'RELIANCE.BSE' for BSE,
                or 'MSFT' for US equities).
        period: Lookback period (converted to outputsize parameter).
        interval: Data interval (default '1d').
        api_key: Alpha Vantage API key.

    Example:
        >>> source = AlphaVantageSource("MSFT", api_key="your_key")
        >>> df = source.fetch()
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        api_key: str = "",
    ):
        super().__init__(symbol, period, interval)
        self.api_key = api_key

    def fetch(self) -> pd.DataFrame:
        """Fetch daily OHLCV data from Alpha Vantage.

        Returns:
            Normalized DataFrame matching BaseDataSource schema.

        Raises:
            NotImplementedError: If api_key is not configured.
            ConnectionError: If the API call fails.
            ValueError: If no data is returned.
        """
        if not self.api_key:
            raise NotImplementedError(
                "Alpha Vantage API key not configured. "
                "Get a free key at https://www.alphavantage.co/support/#api-key "
                "and set ALPHA_VANTAGE_API_KEY in your .env file. "
                "Then pass api_key to AlphaVantageSource or use AppConfig."
            )

        logger.info(
            "Fetching %s from Alpha Vantage (period=%s)",
            self.symbol, self.period,
        )

        # Determine output size based on period
        outputsize = self._period_to_outputsize(self.period)

        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": self.symbol,
            "apikey": self.api_key,
            "outputsize": outputsize,
            "datatype": "json",
        }

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error("Alpha Vantage API call failed for %s: %s", self.symbol, e)
            raise ConnectionError(
                f"Failed to fetch {self.symbol} from Alpha Vantage: {e}"
            ) from e

        # Check for API error messages
        if "Error Message" in data:
            raise ValueError(f"Alpha Vantage error: {data['Error Message']}")
        if "Note" in data:
            logger.warning("Alpha Vantage rate limit note: %s", data["Note"])

        # Parse time series data
        time_series = data.get("Time Series (Daily)", {})
        if not time_series:
            raise ValueError(f"No time series data returned for {self.symbol}")

        # Convert to DataFrame
        rows = []
        cutoff_date = self._period_to_cutoff(self.period)

        for date_str, values in time_series.items():
            trade_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if trade_date >= cutoff_date:
                rows.append({
                    "symbol": self.symbol,
                    "trade_date": trade_date,
                    "open": float(values["1. open"]),
                    "high": float(values["2. high"]),
                    "low": float(values["3. low"]),
                    "close": float(values["4. close"]),
                    "volume": int(values["5. volume"]),
                })

        if not rows:
            raise ValueError(
                f"No data within period {self.period} for {self.symbol}"
            )

        df = pd.DataFrame(rows)
        df = df.sort_values("trade_date").reset_index(drop=True)

        # Validate via base class
        df = self.validate_output(df)

        logger.info(
            "Fetched %d rows for %s from Alpha Vantage (date range: %s to %s)",
            len(df), self.symbol,
            df["trade_date"].min(), df["trade_date"].max(),
        )

        return df

    @staticmethod
    def _period_to_outputsize(period: str) -> str:
        """Convert yfinance-style period to Alpha Vantage outputsize.

        Args:
            period: Period string (e.g. '1mo', '6mo', '1y', '2y').

        Returns:
            'compact' (last 100 days) or 'full' (20+ years).
        """
        # 'compact' returns last ~100 trading days
        # Use 'full' for anything over ~4 months
        short_periods = {"1mo", "2mo", "3mo"}
        return "compact" if period in short_periods else "full"

    @staticmethod
    def _period_to_cutoff(period: str) -> date:
        """Convert period string to a cutoff date for filtering.

        Args:
            period: Period string (e.g. '6mo', '1y').

        Returns:
            Date object representing the earliest date to include.
        """
        today = datetime.now().date()
        period_map = {
            "1mo": timedelta(days=30),
            "2mo": timedelta(days=60),
            "3mo": timedelta(days=90),
            "6mo": timedelta(days=180),
            "1y": timedelta(days=365),
            "2y": timedelta(days=730),
            "5y": timedelta(days=1825),
        }
        delta = period_map.get(period, timedelta(days=180))
        return today - delta

    def __repr__(self) -> str:
        key_status = "configured" if self.api_key else "NOT SET"
        return (
            f"AlphaVantageSource("
            f"symbol={self.symbol!r}, "
            f"period={self.period!r}, "
            f"api_key={key_status})"
        )
