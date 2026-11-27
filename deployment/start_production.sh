#!/usr/bin/env bash
# ==============================================================================
# Ytal Tech Solutions & Services LLP - Production Startup Script (Linux)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "==========================================================="
echo "Starting Ytal Tech E-Learning Production WSGI Server"
echo "Working Directory: $PROJECT_ROOT"
echo "==========================================================="

# Activate virtual environment if present
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Load environment configuration
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

PORT="${PORT:-5000}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-4}"
THREADS="${THREADS:-2}"

echo "Launching Gunicorn on $HOST:$PORT with $WORKERS workers and $THREADS threads..."
exec gunicorn \
    --workers "$WORKERS" \
    --threads "$THREADS" \
    --worker-class gthread \
    --preload \
    --bind "$HOST:$PORT" \
    --timeout 60 \
    wsgi:application
