"""
Scheduled pipeline runner module.

Provides the ScheduledRunner class for automated daily pipeline
execution using the 'schedule' library. Supports graceful shutdown
via signal handlers.

For production Linux deployments, prefer cron (see scripts/setup.sh).
This module is for development or Windows environments where cron
is not available.
"""

import signal
import logging
import time
from datetime import datetime

import schedule

from config.settings import AppConfig
from scheduler.run_pipeline import MarketDataPipeline

logger = logging.getLogger(__name__)


class ScheduledRunner:
    """Runs the pipeline on a daily schedule.

    Uses the 'schedule' library to execute the pipeline at a
    configurable time each day (default: 18:30 IST, after Indian
    market close). Supports graceful shutdown via SIGINT/SIGTERM.

    Args:
        pipeline: MarketDataPipeline instance to run.
        run_time: Daily run time in HH:MM format (24-hour).

    Example:
        >>> config = AppConfig()
        >>> pipeline = MarketDataPipeline(config)
        >>> runner = ScheduledRunner(pipeline, run_time="18:30")
        >>> runner.start()  # Blocks until shutdown signal
    """

    def __init__(self, pipeline: MarketDataPipeline, run_time: str = "18:30"):
        self._pipeline = pipeline
        self._run_time = run_time
        self._shutdown = False

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        logger.info("ScheduledRunner initialized: run_time=%s", self._run_time)

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully.

        Args:
            signum: Signal number received.
            frame: Current stack frame.
        """
        sig_name = signal.Signals(signum).name
        logger.info(
            "Received %s — initiating graceful shutdown...", sig_name
        )
        self._shutdown = True

    def _run_job(self):
        """Execute the pipeline as a scheduled job."""
        logger.info(
            "Scheduled job triggered at %s",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        try:
            self._pipeline.run()
        except SystemExit:
            # Pipeline calls sys.exit on fatal errors; catch here
            # so the scheduler can continue running
            logger.error("Pipeline exited with error. Will retry at next schedule.")
        except Exception as e:
            logger.error("Scheduled run failed: %s", e, exc_info=True)

    def start(self) -> None:
        """Start the scheduling loop (blocks until shutdown signal).

        Schedules the pipeline to run daily at the configured time
        and enters a polling loop. Exits gracefully on SIGINT/SIGTERM.
        """
        schedule.every().day.at(self._run_time).do(self._run_job)

        logger.info(
            "Scheduler started. Pipeline will run daily at %s.",
            self._run_time,
        )
        logger.info(
            "Next run: %s. Press Ctrl+C to stop.",
            schedule.next_run(),
        )

        # Main loop — poll every 30 seconds
        while not self._shutdown:
            schedule.run_pending()
            time.sleep(30)

        # Cleanup
        schedule.clear()
        logger.info("Scheduler stopped gracefully.")

    def stop(self) -> None:
        """Programmatically trigger shutdown."""
        self._shutdown = True

    def __repr__(self) -> str:
        return (
            f"ScheduledRunner("
            f"run_time={self._run_time!r}, "
            f"shutdown={self._shutdown})"
        )


def main():
    """Entry point for the scheduled runner."""
    config = AppConfig()
    config.setup_logging()

    logger.info("Starting scheduled pipeline runner")
    logger.info("Configuration: %s", config)

    pipeline = MarketDataPipeline(config)
    runner = ScheduledRunner(pipeline, run_time=config.SCHEDULE_TIME)
    runner.start()


if __name__ == "__main__":
    main()
