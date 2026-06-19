#!/usr/bin/env bash
# ============================================================
# Market Data Pipeline — Runner Script
# ============================================================
# Activates the virtual environment and runs the pipeline.
# Designed to be called by cron or manually.
#
# Usage:
#   chmod +x scripts/run_pipeline.sh
#   ./scripts/run_pipeline.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Activate venv
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "ERROR: Virtual environment not found. Run scripts/setup.sh first." >&2
    exit 1
fi

# shellcheck source=/dev/null
source "$PROJECT_DIR/venv/bin/activate"

# Change to project directory so imports work
cd "$PROJECT_DIR"

# Run pipeline with any extra arguments passed through
echo "Running pipeline at $(date '+%Y-%m-%d %H:%M:%S')..."
python -m scheduler.run_pipeline "$@"

exit_code=$?
echo "Pipeline finished with exit code $exit_code at $(date '+%Y-%m-%d %H:%M:%S')"
exit $exit_code
