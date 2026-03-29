# LeakyBucket — Burst Congestion Simulation

A 2D microscopic traffic simulation that evaluates ride-share dispatching strategies for clearing high-density passenger bursts (e.g., a stadium emptying after an event). Built on [Eclipse SUMO](https://www.eclipse.org/sumo/) and controlled via Python's `traci` interface.

## The Problem

When thousands of passengers simultaneously request rides from a single location, naive dispatching floods the pickup zone with vehicles, causing gridlock. The simulation defaults to 2,000 passengers and 200 drivers, but scales up to large events (e.g., 40,000+ passengers). It compares three strategies:

- **Baseline (Naive)** — Immediately match each request to the nearest available driver.
- **Leaky Bucket (Rate Limiting)** — Throttle matches using a token bucket to prevent too many vehicles entering the pickup zone at once.
- **Virtual Queuing (Incentivized Smoothing)** — Assign passengers to time-window slots, spreading demand over time.

## KPIs Tracked

| Metric | Description |
|--------|-------------|
| Average Wait Time | Time from request to vehicle assignment |
| 95th% Tail Latency | Wait time for the slowest 5% of riders |
| Clearance Rate | Passengers delivered per 100 simulation steps |
| Gridlock Factor | Average vehicle speed within 500m of the stadium |
| Driver Utilization | Fraction of time drivers spend occupied |
| Braking Intensity | Count of hard-braking events (< -4.5 m/s²) |

## Prerequisites

- **Python 3.10+**
- **macOS / Linux** (Windows should work but is untested)

## Installation

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install Python dependencies (SUMO, traci, streamlit, etc.)
pip install -r requirements.txt

# 3. Set SUMO_HOME (if not already set)
export SUMO_HOME=$(python -c "import sumo; print(sumo.SUMO_HOME)")

# 4. Build the SUMO network (downloads OSM data for Levi's Stadium area)
python -m network.build_network
```

## Quick Start

The easiest way to run the simulation with the live dashboard:

```bash
./run.sh --strategy baseline
```

This launches both the simulation and a Streamlit dashboard at http://localhost:8501 that auto-refreshes with live KPI charts.

To compare all three strategies:

```bash
./run.sh --compare
```

### Scaling Up

Scale the simulation to larger events by adjusting passenger and driver counts:

```bash
# Large-scale event (40,000 passengers, 4,000 drivers)
./run.sh --strategy baseline --passengers 40000 --drivers 4000

# Compare all strategies at scale
./run.sh --compare --passengers 40000 --drivers 4000

# Longer simulation for large bursts
./run.sh --compare --passengers 40000 --drivers 4000 --duration 14400
```

A good rule of thumb is ~1 driver per 10 passengers to ensure reasonable clearance times.

## Manual Usage

If you prefer to run things separately:

```bash
# Run a single strategy
python main.py --strategy baseline
python main.py --strategy leaky_bucket --bucket-size 30 --leak-rate 10
python main.py --strategy virtual_queue --num-slots 20

# Compare all three strategies
python main.py --compare

# Launch the dashboard separately (in another terminal)
streamlit run dashboard.py
```

### SUMO GUI

If you have [XQuartz](https://www.xquartz.org/) installed (macOS), you can use SUMO's built-in visualization:

```bash
open -a XQuartz
export DISPLAY=:0
python main.py --strategy baseline --gui
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--strategy` | `baseline` | `baseline`, `leaky_bucket`, or `virtual_queue` |
| `--gui` | off | Launch sumo-gui (requires XQuartz on macOS) |
| `--duration` | 7200 | Simulation duration in seconds |
| `--passengers` | 2000 | Number of riders in the burst |
| `--drivers` | 200 | Number of drivers in the fleet |
| `--bucket-size` | 30 | Token bucket capacity (leaky bucket only) |
| `--leak-rate` | 10.0 | Tokens released per minute (leaky bucket only) |
| `--num-slots` | 20 | Number of time window slots (virtual queue only) |
| `--slot-duration` | 120 | Seconds per slot (virtual queue only) |
| `--output` | `output/` | Output directory for KPI CSVs and summaries |
| `--compare` | off | Run all strategies and compare results |

## Output

Results are written to the `output/` directory:

- `kpi_<strategy>.csv` — Per-interval KPI snapshots
- `summary.json` — Final simulation summary

## Dashboard

The Streamlit dashboard (`dashboard.py`) provides live visualization of all KPIs. When multiple strategy runs are present, it shows a **Comparison** tab with side-by-side charts and a summary table.

## Project Structure

```
├── agents/          # Person (rider) and Driver agent models
├── dispatchers/     # Pluggable dispatch strategies
├── kpi/             # KPI tracking and CSV export
├── network/         # OSM download and SUMO network generation
├── config.py        # Simulation parameters
├── simulation.py    # Main traci simulation loop
├── dashboard.py     # Streamlit live KPI dashboard
├── main.py          # CLI entry point
└── run.sh           # Launch simulation + dashboard together
```
