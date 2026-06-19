# Market Data Pipeline

An automated Python pipeline that ingests daily OHLCV data for Indian equities, computes derived financial metrics (returns, moving averages, volatility, RSI), persists everything to PostgreSQL with idempotent upserts, and generates matplotlib visualizations — all on a configurable schedule.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐     ┌──────────────┐     ┌────────────────┐
│  Scheduler   │────▶│  Ingestion   │────▶│   Processing     │────▶│   Storage    │────▶│ Visualization  │
│  (cron /     │     │  (yfinance / │     │  (pandas/NumPy)  │     │ (PostgreSQL) │     │  (matplotlib)  │
│   schedule)  │     │  Alpha Vant.)│     │                  │     │              │     │                │
└─────────────┘     └──────────────┘     └──────────────────┘     └──────────────┘     └────────────────┘
       │                    │                     │                       │                      │
       │              LRU Cache              Metrics:                Upsert via             Price + SMA
       │              (OrderedDict)        • daily_return          ON CONFLICT            Volatility
       │                                   • SMA-20/50            DO UPDATE              charts (PNG)
       │                                   • vol_20d (annualized)
       │                                   • RSI-14
       ▼
  JSON run report
  (logs/run_*.json)
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **Stage-then-upsert** | Loads data via temp table + `INSERT ... ON CONFLICT DO UPDATE` — idempotent reruns never duplicate rows |
| **BaseDataSource ABC** | Polymorphic data sources: swap yfinance for Alpha Vantage (or any new source) without touching downstream code |
| **LRU cache (OrderedDict)** | Avoids redundant API calls during retries within a pipeline session; O(1) get/put/evict |
| **Annualized volatility** | `rolling_std × √252` — signals financial time-series fluency, not just `.rolling()` awareness |
| **RSI (Wilder's method)** | Standard 14-period RSI for overbought/oversold detection |
| **Rotating-file logging** | 10 MB per file, 5 backups — production-grade log management |
| **Dual scheduling** | Cron for Linux production; `schedule` library for Windows/dev environments |
| **JSON run reports** | Machine-readable pipeline telemetry via `open()/json.dump()` |

---

## Prerequisites

- **Python 3.10+**
- **PostgreSQL** (running and accessible)
- `pip` for package management

---

## Quick Start

### 1. Clone & setup

```bash
git clone https://github.com/your-username/market-data-pipeline.git
cd market-data-pipeline
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials
```

### 3. Install dependencies

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

### 4. Run the pipeline

```bash
python -m scheduler.run_pipeline
```

### 5. Check output

```bash
ls charts_output/    # PNG charts (2 per symbol)
ls logs/             # Pipeline logs + JSON run reports
```

---

## Linux Setup

```bash
# Make scripts executable
chmod +x scripts/setup.sh scripts/run_pipeline.sh

# Full automated setup (venv + deps + DB + optional cron)
./scripts/setup.sh

# Or run the pipeline manually
./scripts/run_pipeline.sh

# Verify cron schedule
crontab -l

# Monitor pipeline in real-time
tail -f logs/pipeline.log

# Check running pipeline processes
ps aux | grep run_pipeline

# View recent log files
ls -lt logs/ | head -10

# Check disk usage
du -sh logs/ charts_output/
```

---

## Scheduled Execution

### Option A: Cron (Linux/production)

Runs after Indian market close on weekdays:

```bash
# Add to crontab:
0 18 * * 1-5 cd /path/to/project && /path/to/venv/bin/python -m scheduler.run_pipeline >> logs/cron.log 2>&1
```

Or use the setup script: `./scripts/setup.sh` (prompts to add cron automatically).

### Option B: Schedule library (Windows/dev)

```bash
python -m scheduler.loop
# Runs daily at 18:30 (configurable via SCHEDULE_TIME in .env)
# Ctrl+C for graceful shutdown
```

---

## Project Structure

```
market-data-pipeline/
├── config/
│   └── settings.py              # AppConfig class — env loading, logging, paths
├── ingestion/
│   ├── base.py                  # BaseDataSource ABC (polymorphic interface)
│   ├── yfinance_source.py       # YFinanceSource — primary data source with retry
│   └── alpha_vantage_source.py  # AlphaVantageSource — documented fallback
├── processing/
│   └── transformer.py           # MetricsCalculator — returns, SMA, vol, RSI
├── storage/
│   ├── db.py                    # DatabaseManager — connection pool, upsert logic
│   ├── cache.py                 # LRUTickerCache — OrderedDict-based LRU cache
│   └── schema.sql               # PostgreSQL DDL (IF NOT EXISTS)
├── visualization/
│   └── charts.py                # ChartRenderer — price/SMA + volatility PNGs
├── scheduler/
│   ├── run_pipeline.py          # MarketDataPipeline orchestrator class
│   └── loop.py                  # ScheduledRunner — daily schedule via schedule lib
├── scripts/
│   ├── setup.sh                 # Full setup: venv, deps, DB, cron
│   └── run_pipeline.sh          # Runner: activate venv + execute pipeline
├── tests/
│   ├── test_transformer.py      # MetricsCalculator + RSI tests
│   └── test_cache.py            # LRU cache eviction + ordering tests
├── logs/                        # Runtime: pipeline.log, run_*.json
├── charts_output/               # Runtime: {SYMBOL}_price.png, {SYMBOL}_volatility.png
├── .env.example                 # Environment template
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_transformer.py -v
pytest tests/test_cache.py -v

# With coverage (install pytest-cov first)
pytest tests/ -v --cov=processing --cov=storage
```

---

## Watchlist Configuration

Default symbols (Indian equities on NSE):

```env
WATCHLIST=RELIANCE.NS,TCS.NS,INFY.NS
```

For US equities:

```env
WATCHLIST=AAPL,MSFT,GOOGL,AMZN
```

---

## Sample Output

### Pipeline run summary

```
==================================================
  Pipeline Run Summary
==================================================
  Processed: 3 symbols
  Failed:    0 symbols
  Warnings:  0
  Charts:    6
  Runtime:   12.34s
==================================================
```

### Generated charts

Each pipeline run produces two charts per symbol:
- `{SYMBOL}_price.png` — Close price with SMA-20 and SMA-50 overlays
- `{SYMBOL}_volatility.png` — 20-day annualized rolling volatility

---

## Alpha Vantage Fallback

If yfinance is rate-limited, switch to Alpha Vantage:

1. Get a free API key at [alphavantage.co](https://www.alphavantage.co/support/#api-key)
2. Add to `.env`: `ALPHA_VANTAGE_API_KEY=your_key_here`
3. Update the data source in `run_pipeline.py` to use `AlphaVantageSource`

Both sources implement `BaseDataSource`, so swapping is a one-line change with no impact on downstream processing.

---

## Resume Bullet Points

- Built an automated market data pipeline in Python that ingests OHLCV data via yfinance/Alpha Vantage, computes returns, moving averages, volatility, and RSI using pandas/NumPy, and persists results to PostgreSQL with idempotent upserts
- Implemented dual scheduling (cron and subprocess-based) for unattended daily pipeline runs, with retry logic and rotating-file logging for production-grade reliability
- Generated automated matplotlib visualizations (price/SMA overlays, rolling volatility) consumed downstream for analysis
- Designed OOP architecture with ABC-based polymorphic data sources, OrderedDict LRU caching, and stage-then-upsert patterns for pipeline reliability

---

## License

MIT
"# market-data-pipeline" 
