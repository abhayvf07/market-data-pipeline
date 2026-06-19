"""
yfinance data source module.

Implements the YFinanceSource class that fetches OHLCV data from
Yahoo Finance via the yfinance library. Includes retry logic with
exponential backoff for rate-limit resilience.
"""

import logging

import pandas as pd
import yfinance as yf
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from ingestion.base import BaseDataSource

logger = logging.getLogger(__name__)


class YFinanceSource(BaseDataSource):
    """Fetches OHLCV data from Yahoo Finance via yfinance.

    Inherits from BaseDataSource and implements retry logic using
    tenacity for production-grade rate-limit resilience.

    Args:
        symbol: Stock ticker symbol (e.g. 'RELIANCE.NS').
        period: Lookback period (default '6mo').
        interval: Data interval (default '1d').

    Example:
        >>> source = YFinanceSource("RELIANCE.NS", period="6mo")
        >>> df = source.fetch()
        >>> print(df.columns.tolist())
        ['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume']
    """

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, ValueError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def fetch(self) -> pd.DataFrame:
        """Fetch OHLCV data from Yahoo Finance.

        Uses yf.Ticker.history() with configured period and interval.
        Retries up to 3 times with exponential backoff on failure.

        Returns:
            Normalized DataFrame with columns:
            [symbol, trade_date, open, high, low, close, volume]

        Raises:
            ValueError: If no data is returned for the symbol.
            ConnectionError: If the API call fails after all retries.
        """
        logger.info(
            "Fetching %s from Yahoo Finance (period=%s, interval=%s)",
            self.symbol, self.period, self.interval,
        )

        try:
            ticker = yf.Ticker(self.symbol)
            df = ticker.history(period=self.period, interval=self.interval)
        except Exception as e:
            logger.error("yfinance API call failed for %s: %s", self.symbol, e)
            raise ConnectionError(
                f"Failed to fetch {self.symbol} from Yahoo Finance: {e}"
            ) from e

        if df.empty:
            raise ValueError(f"No data returned for {self.symbol}")

        # Normalize column names and structure
        df = df.reset_index()
        df.columns = [col.lower() for col in df.columns]

        # Rename 'date' to 'trade_date' for schema consistency
        if "date" in df.columns:
            df = df.rename(columns={"date": "trade_date"})
        elif "datetime" in df.columns:
            df = df.rename(columns={"datetime": "trade_date"})

        # Ensure trade_date is date-only (not datetime with timezone)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        # Add symbol column
        df["symbol"] = self.symbol

        # Validate and return only required columns
        df = self.validate_output(df)

        logger.info(
            "Fetched %d rows for %s (date range: %s to %s)",
            len(df), self.symbol,
            df["trade_date"].min(), df["trade_date"].max(),
        )

        return df
