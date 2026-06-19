"""
Application configuration module.

Loads environment variables from .env, constructs the database DSN,
sets up rotating-file logging, and exposes pipeline settings.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote_plus
from dotenv import load_dotenv


class AppConfig:
    """Centralized configuration for the Market Data Pipeline.

    Loads settings from environment variables (via .env file) and provides
    validated, typed access to all pipeline configuration.

    Attributes:
        WATCHLIST (list[str]): Stock symbols to track.
        FETCH_PERIOD (str): yfinance period string (e.g. '6mo').
        FETCH_INTERVAL (str): yfinance interval string (e.g. '1d').
        SCHEDULE_TIME (str): Daily run time in HH:MM format.
    """

    # --- Defaults ---
    DEFAULT_WATCHLIST = ["RELIANCE.NS", "TCS.NS", "INFY.NS"]
    DEFAULT_FETCH_PERIOD = "6mo"
    DEFAULT_FETCH_INTERVAL = "1d"
    DEFAULT_SCHEDULE_TIME = "18:30"

    def __init__(self, env_path: str | None = None):
        """Initialize configuration by loading .env and validating settings.

        Args:
            env_path: Optional path to .env file. Defaults to project root.
        """
        project_root = Path(__file__).resolve().parent.parent
        env_file = env_path or project_root / ".env"
        load_dotenv(env_file)

        # Validate required DB settings
        self._db_host = os.getenv("DB_HOST", "localhost")
        self._db_port = os.getenv("DB_PORT", "5432")
        self._db_name = os.getenv("DB_NAME", "market_data")
        self._db_user = os.getenv("DB_USER", "postgres")
        self._db_password = os.getenv("DB_PASSWORD", "")

        if not self._db_password:
            logging.warning(
                "DB_PASSWORD is empty. Set it in .env for production use."
            )

        # Pipeline settings
        watchlist_str = os.getenv("WATCHLIST", "")
        self.WATCHLIST = (
            [s.strip() for s in watchlist_str.split(",") if s.strip()]
            if watchlist_str
            else self.DEFAULT_WATCHLIST
        )
        self.FETCH_PERIOD = os.getenv("FETCH_PERIOD", self.DEFAULT_FETCH_PERIOD)
        self.FETCH_INTERVAL = os.getenv("FETCH_INTERVAL", self.DEFAULT_FETCH_INTERVAL)
        self.SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", self.DEFAULT_SCHEDULE_TIME)

        # Optional Alpha Vantage key
        self.ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

        # Create runtime directories (explicit os usage)
        self._project_root = project_root
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.charts_dir, exist_ok=True)

    @property
    def db_dsn(self) -> str:
        """SQLAlchemy-compatible PostgreSQL connection string.

        URL-encodes the password so special characters like @, #, %
        don't break the DSN parsing.
        """
        encoded_password = quote_plus(self._db_password)
        return (
            f"postgresql+psycopg2://{self._db_user}:{encoded_password}"
            f"@{self._db_host}:{self._db_port}/{self._db_name}"
        )

    @property
    def log_dir(self) -> str:
        """Absolute path to the logs directory."""
        return str(self._project_root / "logs")

    @property
    def charts_dir(self) -> str:
        """Absolute path to the charts output directory."""
        return str(self._project_root / "charts_output")

    @property
    def schema_path(self) -> str:
        """Absolute path to the SQL schema file."""
        return str(self._project_root / "storage" / "schema.sql")

    def setup_logging(self, level: int = logging.INFO) -> None:
        """Configure rotating-file and console logging.

        Args:
            level: Logging level (default: INFO).
        """
        log_file = os.path.join(self.log_dir, "pipeline.log")

        # Root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        # Prevent duplicate handlers on repeated calls
        if root_logger.handlers:
            return

        # Rotating file handler: 10 MB per file, keep 5 backups
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S",
        )
        console_handler.setFormatter(console_format)

        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    def __repr__(self) -> str:
        """Config summary with masked password."""
        masked_pw = "*" * len(self._db_password) if self._db_password else "(empty)"
        return (
            f"AppConfig(\n"
            f"  db={self._db_user}@{self._db_host}:{self._db_port}/{self._db_name} "
            f"pw={masked_pw}\n"
            f"  watchlist={self.WATCHLIST}\n"
            f"  period={self.FETCH_PERIOD}, interval={self.FETCH_INTERVAL}\n"
            f"  schedule={self.SCHEDULE_TIME}\n"
            f")"
        )
