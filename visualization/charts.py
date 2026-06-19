"""
Chart generation module.

Provides the ChartRenderer class for creating financial visualizations:
price + SMA overlay charts and rolling volatility charts.
"""

import os
import logging
from datetime import datetime

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server/pipeline use
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logger = logging.getLogger(__name__)


class ChartRenderer:
    """Generates financial charts from enriched OHLCV data.

    Produces two chart types per symbol:
    1. Price with SMA-20/SMA-50 overlay
    2. Rolling 20-day annualized volatility

    Args:
        df: DataFrame with columns [trade_date, close, sma_20, sma_50, volatility_20d].
        symbol: Stock ticker symbol for chart titles and filenames.
        output_dir: Directory to save chart PNGs.

    Example:
        >>> renderer = ChartRenderer(enriched_df, "RELIANCE.NS")
        >>> paths = renderer.render_all()
        >>> print(paths)
        ['charts_output/RELIANCE.NS_price.png', 'charts_output/RELIANCE.NS_volatility.png']
    """

    # Chart style configuration
    STYLE = "seaborn-v0_8-darkgrid"
    FIGURE_SIZE = (12, 6)
    DPI = 150
    PRICE_COLOR = "#1f77b4"
    SMA20_COLOR = "#ff7f0e"
    SMA50_COLOR = "#2ca02c"
    VOLATILITY_COLOR = "#d62728"

    def __init__(
        self,
        df: pd.DataFrame,
        symbol: str,
        output_dir: str = "charts_output",
    ):
        self._df = df.copy()
        self._symbol = symbol
        self._output_dir = output_dir

        # Ensure output directory exists (explicit os usage)
        os.makedirs(self._output_dir, exist_ok=True)

        # Convert trade_date to datetime for matplotlib compatibility
        if "trade_date" in self._df.columns:
            self._df["trade_date"] = pd.to_datetime(self._df["trade_date"])

        logger.debug(
            "ChartRenderer initialized for %s (%d data points, output=%s)",
            self._symbol, len(self._df), self._output_dir,
        )

    def plot_price_with_sma(self) -> str:
        """Generate price chart with SMA-20 and SMA-50 overlays.

        Returns:
            Path to the saved PNG file.
        """
        try:
            plt.style.use(self.STYLE)
        except OSError:
            logger.debug("Style %s not available, using default.", self.STYLE)

        fig, ax = plt.subplots(figsize=self.FIGURE_SIZE)

        # Plot closing price
        ax.plot(
            self._df["trade_date"],
            self._df["close"],
            label="Close",
            color=self.PRICE_COLOR,
            linewidth=1.5,
            alpha=0.9,
        )

        # Plot SMA-20
        if "sma_20" in self._df.columns:
            ax.plot(
                self._df["trade_date"],
                self._df["sma_20"],
                label="SMA 20",
                color=self.SMA20_COLOR,
                linestyle="--",
                linewidth=1.0,
                alpha=0.8,
            )

        # Plot SMA-50
        if "sma_50" in self._df.columns:
            ax.plot(
                self._df["trade_date"],
                self._df["sma_50"],
                label="SMA 50",
                color=self.SMA50_COLOR,
                linestyle="--",
                linewidth=1.0,
                alpha=0.8,
            )

        # Formatting
        ax.set_title(
            f"{self._symbol} — Price with Moving Averages",
            fontsize=14,
            fontweight="bold",
            pad=15,
        )
        ax.set_xlabel("Date", fontsize=11)
        ax.set_ylabel("Price", fontsize=11)
        ax.legend(loc="upper left", fontsize=10)
        ax.grid(True, alpha=0.3)

        # Date formatting on x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        fig.autofmt_xdate(rotation=45)

        # Add timestamp watermark
        fig.text(
            0.99, 0.01,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            fontsize=7, ha="right", va="bottom", alpha=0.5,
        )

        # Save
        output_path = os.path.join(self._output_dir, f"{self._symbol}_price.png")
        fig.savefig(output_path, dpi=self.DPI, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        logger.info("Price chart saved: %s", output_path)
        return output_path

    def plot_volatility(self) -> str:
        """Generate 20-day annualized rolling volatility chart.

        Returns:
            Path to the saved PNG file.
        """
        if "volatility_20d" not in self._df.columns:
            logger.warning(
                "volatility_20d column missing for %s — skipping volatility chart.",
                self._symbol,
            )
            return ""

        try:
            plt.style.use(self.STYLE)
        except OSError:
            pass

        fig, ax = plt.subplots(figsize=self.FIGURE_SIZE)

        ax.plot(
            self._df["trade_date"],
            self._df["volatility_20d"] * 100,  # Convert to percentage
            label="20-Day Annualized Volatility",
            color=self.VOLATILITY_COLOR,
            linewidth=1.5,
            alpha=0.9,
        )

        # Add fill for visual emphasis
        ax.fill_between(
            self._df["trade_date"],
            self._df["volatility_20d"] * 100,
            alpha=0.15,
            color=self.VOLATILITY_COLOR,
        )

        # Formatting
        ax.set_title(
            f"{self._symbol} — Rolling Volatility (20-Day, Annualized)",
            fontsize=14,
            fontweight="bold",
            pad=15,
        )
        ax.set_xlabel("Date", fontsize=11)
        ax.set_ylabel("Volatility (%)", fontsize=11)
        ax.legend(loc="upper right", fontsize=10)
        ax.grid(True, alpha=0.3)

        # Date formatting
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        fig.autofmt_xdate(rotation=45)

        # Timestamp watermark
        fig.text(
            0.99, 0.01,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            fontsize=7, ha="right", va="bottom", alpha=0.5,
        )

        # Save
        output_path = os.path.join(
            self._output_dir, f"{self._symbol}_volatility.png"
        )
        fig.savefig(output_path, dpi=self.DPI, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        logger.info("Volatility chart saved: %s", output_path)
        return output_path

    def render_all(self) -> list[str]:
        """Generate all chart types for the symbol.

        Returns:
            List of paths to saved PNG files.
        """
        paths = []
        paths.append(self.plot_price_with_sma())
        vol_path = self.plot_volatility()
        if vol_path:
            paths.append(vol_path)

        logger.info(
            "Rendered %d charts for %s: %s",
            len(paths), self._symbol, paths,
        )
        return paths

    def __repr__(self) -> str:
        return (
            f"ChartRenderer("
            f"symbol={self._symbol!r}, "
            f"rows={len(self._df)}, "
            f"output_dir={self._output_dir!r})"
        )
