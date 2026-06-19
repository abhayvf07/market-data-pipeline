"""
Pipeline orchestrator module.

Provides the MarketDataPipeline class that coordinates the full
fetch → process → validate → store → chart workflow for each
symbol in the watchlist.
"""

import sys
import os
import json
import logging
from datetime import datetime

from config.settings import AppConfig
from ingestion.yfinance_source import YFinanceSource
from processing.transformer import MetricsCalculator
from storage.db import DatabaseManager
from storage.cache import LRUTickerCache
from visualization.charts import ChartRenderer

logger = logging.getLogger(__name__)


class MarketDataPipeline:
    """Orchestrates the full market data pipeline.

    Workflow per symbol:
    1. Check LRU cache for recent data
    2. Fetch OHLCV via YFinanceSource (with retry)
    3. Compute metrics via MetricsCalculator
    4. Validate data (flag anomalies)
    5. Upsert prices + metrics to PostgreSQL
    6. Generate charts

    After all symbols: write a JSON run report to logs/.

    Args:
        config: AppConfig instance with all pipeline settings.

    Example:
        >>> config = AppConfig()
        >>> pipeline = MarketDataPipeline(config)
        >>> results = pipeline.run()
    """

    def __init__(self, config: AppConfig):
        self._config = config
        self._db = DatabaseManager(config.db_dsn)
        self._cache = LRUTickerCache(capacity=32)
        self._run_start: datetime | None = None

        logger.info("MarketDataPipeline initialized: %s", self)

    def run(self) -> dict:
        """Execute the full pipeline for all symbols in the watchlist.

        Returns:
            Summary dict with keys: symbols_processed, symbols_failed,
            total_rows, warnings, runtime_seconds, charts_generated.
        """
        self._run_start = datetime.now()
        logger.info(
            "=" * 60 + "\n  Pipeline run started at %s\n  Watchlist: %s\n" + "=" * 60,
            self._run_start.strftime("%Y-%m-%d %H:%M:%S"),
            self._config.WATCHLIST,
        )

        results = {
            "run_timestamp": self._run_start.isoformat(),
            "symbols_processed": [],
            "symbols_failed": [],
            "total_price_rows": 0,
            "total_metric_rows": 0,
            "warnings": [],
            "charts_generated": [],
            "runtime_seconds": 0,
        }

        # Initialize DB schema (idempotent)
        try:
            self._db.init_db(self._config.schema_path)
        except Exception as e:
            logger.critical("Database initialization failed: %s", e)
            self._save_run_report(results)
            sys.exit(1)  # Explicit sys usage — fatal error

        # Process each symbol
        for symbol in self._config.WATCHLIST:
            try:
                self._process_symbol(symbol, results)
                results["symbols_processed"].append(symbol)
            except Exception as e:
                logger.error("Failed to process %s: %s", symbol, e, exc_info=True)
                results["symbols_failed"].append({"symbol": symbol, "error": str(e)})

        # Calculate runtime
        runtime = (datetime.now() - self._run_start).total_seconds()
        results["runtime_seconds"] = round(runtime, 2)

        # Save run report (explicit file handling)
        self._save_run_report(results)

        # Summary log
        logger.info(
            "Pipeline run complete in %.2fs — "
            "%d symbols processed, %d failed, %d warnings",
            runtime,
            len(results["symbols_processed"]),
            len(results["symbols_failed"]),
            len(results["warnings"]),
        )

        # Exit with error code if all symbols failed
        if not results["symbols_processed"] and results["symbols_failed"]:
            logger.critical("All symbols failed. Check logs for details.")
            sys.exit(1)

        return results

    def _process_symbol(self, symbol: str, results: dict) -> None:
        """Process a single symbol through the full pipeline.

        Args:
            symbol: Stock ticker symbol.
            results: Mutable results dict to update.
        """
        logger.info("--- Processing %s ---", symbol)

        # Step 1: Check cache
        cached = self._cache.get(symbol, self._config.FETCH_PERIOD)
        if cached is not None:
            logger.info("Using cached data for %s (%d rows)", symbol, len(cached))
            raw_df = cached
        else:
            # Step 2: Fetch from data source
            source = YFinanceSource(
                symbol,
                period=self._config.FETCH_PERIOD,
                interval=self._config.FETCH_INTERVAL,
            )
            raw_df = source.fetch()
            self._cache.put(symbol, self._config.FETCH_PERIOD, raw_df)

        # Step 3: Compute metrics
        calculator = MetricsCalculator(raw_df)
        enriched_df = calculator.compute()

        # Step 4: Validate
        warnings = calculator.validate()
        results["warnings"].extend(warnings)

        # Step 5: Upsert to database
        price_rows = self._db.upsert_prices(enriched_df)
        metric_rows = self._db.upsert_metrics(enriched_df)
        results["total_price_rows"] += price_rows
        results["total_metric_rows"] += metric_rows

        # Step 6: Generate charts
        renderer = ChartRenderer(
            enriched_df, symbol, output_dir=self._config.charts_dir
        )
        chart_paths = renderer.render_all()
        results["charts_generated"].extend(chart_paths)

        logger.info(
            "%s complete: %d price rows, %d metric rows, %d charts",
            symbol, price_rows, metric_rows, len(chart_paths),
        )

    def _save_run_report(self, results: dict) -> str:
        """Write a JSON summary of the pipeline run to logs/.

        Demonstrates explicit file handling with open()/json.dump().

        Args:
            results: Pipeline run results dict.

        Returns:
            Path to the saved report file.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(
            self._config.log_dir, f"run_{timestamp}.json"
        )

        # Explicit file handling with open() and json.dump()
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)

        logger.info("Run report saved: %s", report_path)
        return report_path

    def __repr__(self) -> str:
        return (
            f"MarketDataPipeline(\n"
            f"  watchlist={self._config.WATCHLIST},\n"
            f"  db={self._db!r},\n"
            f"  cache={self._cache!r}\n"
            f")"
        )


def main():
    """Entry point for the pipeline."""
    config = AppConfig()
    config.setup_logging()

    logger.info("Starting Market Data Pipeline")
    logger.info("Configuration: %s", config)

    pipeline = MarketDataPipeline(config)
    results = pipeline.run()

    # Print summary to stdout
    print(f"\n{'=' * 50}")
    print(f"  Pipeline Run Summary")
    print(f"{'=' * 50}")
    print(f"  Processed: {len(results['symbols_processed'])} symbols")
    print(f"  Failed:    {len(results['symbols_failed'])} symbols")
    print(f"  Warnings:  {len(results['warnings'])}")
    print(f"  Charts:    {len(results['charts_generated'])}")
    print(f"  Runtime:   {results['runtime_seconds']}s")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
