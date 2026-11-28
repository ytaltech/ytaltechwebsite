#!/usr/bin/env bash
# ==============================================================================
# Ytal Tech Solutions & Services LLP - Production Startup Script (Linux)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "==========================================================="
echo "Starting Ytal Tech Production WSGI Server"
echo "Working Directory: $PROJECT_ROOT"
echo "==========================================================="

# Activate virtual environment if present
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Load environment configuration from config loader
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

PORT="${PORT:-5001}"
HOST="${HOST:-127.0.0.1}"
WORKERS="${WORKERS:-4}"
THREADS="${THREADS:-2}"

echo "Launching Gunicorn on $HOST:$PORT with $WORKERS workers and $THREADS threads (no --preload)..."
exec gunicorn \
    --workers "$WORKERS" \
    --threads "$THREADS" \
    --worker-class gthread \
    --bind "$HOST:$PORT" \
    --timeout 60 \
    wsgi:application
