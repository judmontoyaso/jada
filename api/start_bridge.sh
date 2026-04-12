#!/bin/bash

# start_bridge.sh - Run the Voice Bridge API

# Resolve absolute path to Jada root directory
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
JADA_DIR="$(dirname "$SCRIPT_DIR")"

echo "🚀 Starting Jada Voice Bridge on port 8001..."

# Activate virtual environment if it exists
if [ -d "$JADA_DIR/.venv" ]; then
    echo "Activating virtual environment..."
    source "$JADA_DIR/.venv/bin/activate"
fi

# Change to JADA_DIR to ensure proper Python path and .env loading
cd "$JADA_DIR" || exit 1

# Start the uvicorn server serving the voice_bridge app
# We use uvicorn directly. The app is in api/voice_bridge.py
exec uvicorn api.voice_bridge:app --host 0.0.0.0 --port 8002
