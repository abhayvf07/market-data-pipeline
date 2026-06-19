"""
Database management module.

Provides the DatabaseManager class for PostgreSQL interactions:
engine caching, schema initialization, and stage-then-upsert
operations for idempotent data loading.
"""

import logging
from sqlalchemy import create_engine, text, String, Date, Numeric, BigInteger
from sqlalchemy.engine import Engine
import pandas as pd

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages PostgreSQL connections and data persistence.

    Uses SQLAlchemy engine caching and a stage-then-upsert pattern
    for idempotent pipeline reruns.

    Args:
        dsn: SQLAlchemy-compatible PostgreSQL connection string.
    """

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._engine: Engine | None = None
        logger.info("DatabaseManager initialized for %s", self._safe_dsn)

    @property
    def engine(self) -> Engine:
        """Lazily-created, cached SQLAlchemy engine."""
        if self._engine is None:
            self._engine = create_engine(
                self._dsn,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
            logger.info("SQLAlchemy engine created: %s", self._safe_dsn)
        return self._engine

    @property
    def _safe_dsn(self) -> str:
        """DSN string with password masked for logging."""
        try:
            # Mask password between :// user : password @ host
            parts = self._dsn.split("@")
            if len(parts) == 2:
                prefix = parts[0]
                # Find last : in prefix (separates user:password)
                colon_idx = prefix.rfind(":")
                if colon_idx > 0:
                    return prefix[:colon_idx] + ":****@" + parts[1]
        except Exception:
            pass
        return "(dsn hidden)"

    def init_db(self, schema_path: str | None = None) -> None:
        """Execute schema.sql to create tables (idempotent).

        Reads the DDL file using open() and executes it within
        a transactional context.

        Args:
            schema_path: Path to schema.sql. Auto-detected if None.
        """
        if schema_path is None:
            from config.settings import AppConfig
            schema_path = AppConfig().schema_path

        logger.info("Initializing database schema from %s", schema_path)

        # Explicit file handling with open()/read()
        with open(schema_path, "r", encoding="utf-8") as f:
            ddl = f.read()

        with self.engine.begin() as conn:
            # Execute each statement separately (split on semicolons)
            for statement in ddl.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(text(statement))

        logger.info("Database schema initialized successfully.")

    def upsert_prices(self, df: pd.DataFrame) -> int:
        """Upsert OHLCV price data using stage-then-upsert pattern.

        Loads data into a staging table, then merges into stock_prices
        using INSERT ... ON CONFLICT DO UPDATE for idempotent reruns.

        Args:
            df: DataFrame with columns [symbol, trade_date, open, high, low, close, volume].

        Returns:
            Number of rows upserted.
        """
        price_cols = ["symbol", "trade_date", "open", "high", "low", "close", "volume"]
        staging_df = df[price_cols].copy()
        staging_df = staging_df.dropna(subset=["symbol", "trade_date"])

        # Ensure trade_date is proper date type for PostgreSQL
        staging_df["trade_date"] = pd.to_datetime(staging_df["trade_date"]).dt.date

        row_count = len(staging_df)
        if row_count == 0:
            logger.warning("No price data to upsert.")
            return 0

        # Stage data with explicit column types to match target schema
        # This prevents pandas from creating TEXT columns where DATE/NUMERIC is needed
        dtype_map = {
            "symbol": String(20),
            "trade_date": Date(),
            "open": Numeric(12, 4),
            "high": Numeric(12, 4),
            "low": Numeric(12, 4),
            "close": Numeric(12, 4),
            "volume": BigInteger(),
        }
        staging_df.to_sql(
            "stock_prices_staging",
            self.engine,
            if_exists="replace",
            index=False,
            dtype=dtype_map,
            method="multi",
        )

        upsert_sql = text("""
            INSERT INTO stock_prices (symbol, trade_date, open, high, low, close, volume)
            SELECT symbol, trade_date, open, high, low, close, volume
            FROM stock_prices_staging
            ON CONFLICT (symbol, trade_date) DO UPDATE SET
                open   = EXCLUDED.open,
                high   = EXCLUDED.high,
                low    = EXCLUDED.low,
                close  = EXCLUDED.close,
                volume = EXCLUDED.volume
        """)

        with self.engine.begin() as conn:
            conn.execute(upsert_sql)
            # Clean up staging table
            conn.execute(text("DROP TABLE IF EXISTS stock_prices_staging"))

        logger.info("Upserted %d price rows.", row_count)
        return row_count

    def upsert_metrics(self, df: pd.DataFrame) -> int:
        """Upsert computed metrics using stage-then-upsert pattern.

        Args:
            df: DataFrame with columns [symbol, trade_date, daily_return,
                sma_20, sma_50, volatility_20d, rsi_14].

        Returns:
            Number of rows upserted.
        """
        metric_cols = [
            "symbol", "trade_date", "daily_return",
            "sma_20", "sma_50", "volatility_20d", "rsi_14",
        ]
        staging_df = df[metric_cols].copy()
        staging_df = staging_df.dropna(subset=["symbol", "trade_date"])

        # Ensure trade_date is proper date type for PostgreSQL
        staging_df["trade_date"] = pd.to_datetime(staging_df["trade_date"]).dt.date

        row_count = len(staging_df)
        if row_count == 0:
            logger.warning("No metrics data to upsert.")
            return 0

        # Explicit column types matching the target stock_metrics schema
        dtype_map = {
            "symbol": String(20),
            "trade_date": Date(),
            "daily_return": Numeric(8, 5),
            "sma_20": Numeric(12, 4),
            "sma_50": Numeric(12, 4),
            "volatility_20d": Numeric(8, 5),
            "rsi_14": Numeric(6, 2),
        }
        staging_df.to_sql(
            "stock_metrics_staging",
            self.engine,
            if_exists="replace",
            index=False,
            dtype=dtype_map,
            method="multi",
        )

        upsert_sql = text("""
            INSERT INTO stock_metrics
                (symbol, trade_date, daily_return, sma_20, sma_50, volatility_20d, rsi_14)
            SELECT symbol, trade_date, daily_return, sma_20, sma_50, volatility_20d, rsi_14
            FROM stock_metrics_staging
            ON CONFLICT (symbol, trade_date) DO UPDATE SET
                daily_return   = EXCLUDED.daily_return,
                sma_20         = EXCLUDED.sma_20,
                sma_50         = EXCLUDED.sma_50,
                volatility_20d = EXCLUDED.volatility_20d,
                rsi_14         = EXCLUDED.rsi_14
        """)

        with self.engine.begin() as conn:
            conn.execute(upsert_sql)
            conn.execute(text("DROP TABLE IF EXISTS stock_metrics_staging"))

        logger.info("Upserted %d metrics rows.", row_count)
        return row_count

    def close(self) -> None:
        """Dispose of the engine and release all connections."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            logger.info("Database engine disposed.")

    def __repr__(self) -> str:
        return f"DatabaseManager(dsn={self._safe_dsn})"
