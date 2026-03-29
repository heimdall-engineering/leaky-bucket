#!/usr/bin/env bash
# Run the simulation with SUMO GUI and live Streamlit dashboard together.
# Usage:
#   ./run.sh --strategy baseline
#   ./run.sh --strategy leaky_bucket --bucket-size 30
#   ./run.sh --compare

set -e

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ] && [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Check if --compare mode (skip GUI since multiple SUMO instances run)
IS_COMPARE=false
for arg in "$@"; do
    if [ "$arg" = "--compare" ]; then
        IS_COMPARE=true
        break
    fi
done

# Set up XQuartz for SUMO GUI (single strategy only)
if [ "$IS_COMPARE" = false ]; then
    open -a XQuartz 2>/dev/null || true
    export DISPLAY=:0
    GUI_FLAG="--gui"
else
    GUI_FLAG=""
fi

# Cleanup background processes on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $SIM_PID $DASH_PID 2>/dev/null
    wait $SIM_PID $DASH_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start the Streamlit dashboard in the background
streamlit run dashboard.py --server.headless true &
DASH_PID=$!

# Give Streamlit a moment to start
sleep 2

# Run the simulation (passes all args through)
python main.py $GUI_FLAG "$@" &
SIM_PID=$!

if [ "$IS_COMPARE" = true ]; then
    echo "Running all 3 strategies in parallel..."
else
    echo "SUMO GUI:   launching..."
fi
echo "Dashboard:  http://localhost:8501"
echo "Press Ctrl+C to stop both."
echo ""

wait $SIM_PID
echo "Simulation complete. Dashboard still running — press Ctrl+C to stop."
wait $DASH_PID
