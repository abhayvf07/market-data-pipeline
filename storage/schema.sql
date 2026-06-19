-- ============================================================
-- Market Data Pipeline — Database Schema
-- ============================================================
-- Idempotent DDL: safe to re-run (IF NOT EXISTS guards).
-- Composite PKs on (symbol, trade_date) enable upsert-based
-- pipeline reruns without row duplication.
-- ============================================================

-- Raw OHLCV price data
CREATE TABLE IF NOT EXISTS stock_prices (
    symbol      VARCHAR(20)     NOT NULL,
    trade_date  DATE            NOT NULL,
    open        NUMERIC(12, 4),
    high        NUMERIC(12, 4),
    low         NUMERIC(12, 4),
    close       NUMERIC(12, 4),
    volume      BIGINT,
    PRIMARY KEY (symbol, trade_date)
);

-- Computed financial metrics derived from stock_prices
CREATE TABLE IF NOT EXISTS stock_metrics (
    symbol          VARCHAR(20)     NOT NULL,
    trade_date      DATE            NOT NULL,
    daily_return    NUMERIC(8, 5),
    sma_20          NUMERIC(12, 4),
    sma_50          NUMERIC(12, 4),
    volatility_20d  NUMERIC(8, 5),
    rsi_14          NUMERIC(6, 2),
    PRIMARY KEY (symbol, trade_date),
    FOREIGN KEY (symbol, trade_date)
        REFERENCES stock_prices (symbol, trade_date)
        ON DELETE CASCADE
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_prices_symbol
    ON stock_prices (symbol);

CREATE INDEX IF NOT EXISTS idx_prices_date
    ON stock_prices (trade_date);

CREATE INDEX IF NOT EXISTS idx_metrics_symbol
    ON stock_metrics (symbol);

CREATE INDEX IF NOT EXISTS idx_metrics_date
    ON stock_metrics (trade_date);
