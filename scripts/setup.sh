#!/usr/bin/env bash
# ============================================================
# Market Data Pipeline — Setup Script
# ============================================================
# Creates Python venv, installs dependencies, initializes the
# database, and optionally schedules a cron job.
#
# Usage:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh
#
# Prerequisites:
#   - Python 3.10+
#   - PostgreSQL running and accessible
#   - .env file configured (copied from .env.example)
# ============================================================

set -euo pipefail

# --- Resolve paths ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "  Market Data Pipeline — Setup"
echo "============================================"
echo "  Project directory: $PROJECT_DIR"
echo ""

# --- Step 1: Create virtual environment ---
echo "[1/5] Creating Python virtual environment..."
if [ -d "$PROJECT_DIR/venv" ]; then
    echo "  → venv already exists, skipping creation."
else
    python3 -m venv "$PROJECT_DIR/venv"
    echo "  → venv created at $PROJECT_DIR/venv"
fi

# Activate venv
# shellcheck source=/dev/null
source "$PROJECT_DIR/venv/bin/activate"
echo "  → Activated venv (Python: $(python3 --version))"

# --- Step 2: Install dependencies ---
echo ""
echo "[2/5] Installing dependencies..."
pip install --upgrade pip --quiet
pip install -r "$PROJECT_DIR/requirements.txt" --quiet
echo "  → $(pip list --format=columns | wc -l) packages installed."

# --- Step 3: Create runtime directories ---
echo ""
echo "[3/5] Creating runtime directories..."
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$PROJECT_DIR/charts_output"
echo "  → logs/ and charts_output/ ready."

# --- Step 4: Configure environment ---
echo ""
echo "[4/5] Checking environment configuration..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "  ⚠  Created .env from template."
    echo "  ⚠  IMPORTANT: Edit $PROJECT_DIR/.env with your DB credentials before running the pipeline."
    echo ""
    read -rp "  Press Enter after editing .env, or Ctrl+C to abort..."
fi
echo "  → .env file found."

# --- Step 5: Initialize database ---
echo ""
echo "[5/5] Initializing database schema..."
cd "$PROJECT_DIR"
python3 -c "
from config.settings import AppConfig
from storage.db import DatabaseManager

config = AppConfig()
db = DatabaseManager(config.db_dsn)
db.init_db(config.schema_path)
print('  → Database schema initialized successfully.')
db.close()
"

# --- Optional: Schedule cron job ---
echo ""
read -rp "Schedule daily cron job? (y/N): " schedule_cron

if [[ "$schedule_cron" =~ ^[Yy]$ ]]; then
    PYTHON_PATH="$PROJECT_DIR/venv/bin/python"
    CRON_CMD="30 18 * * 1-5 cd $PROJECT_DIR && $PYTHON_PATH -m scheduler.run_pipeline >> $PROJECT_DIR/logs/cron.log 2>&1"

    # Remove any existing pipeline cron entry, then add the new one
    (crontab -l 2>/dev/null | grep -v "run_pipeline" || true; echo "$CRON_CMD") | crontab -

    echo "  → Cron job scheduled: weekdays at 18:30"
    echo "  → Verify with: crontab -l"
    echo "  → Monitor with: tail -f $PROJECT_DIR/logs/cron.log"
else
    echo "  → Skipped cron scheduling."
    echo "  → You can run manually: python -m scheduler.run_pipeline"
    echo "  → Or use the schedule loop: python -m scheduler.loop"
fi

echo ""
echo "============================================"
echo "  ✓ Setup complete!"
echo "============================================"
echo ""
echo "  Quick start:"
echo "    source venv/bin/activate"
echo "    python -m scheduler.run_pipeline"
echo ""
echo "  Useful commands:"
echo "    tail -f logs/pipeline.log     # Live log monitoring"
echo "    ls -lt charts_output/         # View generated charts"
echo "    crontab -l                    # Check scheduled jobs"
echo "    ps aux | grep run_pipeline    # Check running processes"
echo ""
