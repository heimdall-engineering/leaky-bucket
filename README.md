# LeakyBucket — Burst Congestion Simulation

A 2D microscopic traffic simulation that evaluates ride-share dispatching strategies for clearing high-density passenger bursts (e.g., a stadium emptying after an event). Built on [Eclipse SUMO](https://www.eclipse.org/sumo/) and controlled via Python's `traci` interface.

## The Problem

When thousands of passengers simultaneously request rides from a single location, naive dispatching floods the pickup zone with vehicles, causing gridlock. The simulation defaults to 2,000 passengers and 200 drivers, but scales up to large events (e.g., 40,000+ passengers). It compares six dispatch strategies:

- **Baseline (Naive)** — Immediately match each request to the nearest available driver.
- **Leaky Bucket (Rate Limiting)** — Throttle matches using a token bucket to prevent too many vehicles entering the pickup zone at once.
- **Virtual Queuing (Incentivized Smoothing)** — Assign passengers to time-window slots, spreading demand over time.
- **Wave Dispatching** — Release drivers in coordinated waves, waiting for a completion threshold before sending the next batch.
- **Adaptive Rate Limiting** — Token bucket where the refill rate self-tunes based on how many drivers are idle vs. busy.
- **Surge Pricing (Demand Shaping)** — Simulate dynamic pricing where high queue lengths cause riders to probabilistically defer, naturally smoothing demand.

## KPI Dashboard (Three-Panel Layout)

### 1. Rider Experience (Pain Metrics)

| Metric | Description |
|--------|-------------|
| Average Wait Time (AWT) | Time from request to vehicle assignment |
| 95th% Tail Latency | Wait time for the slowest 5% of riders |
| ETR (Estimated Time to Request) | Time spent queued before being matched |
| Match Failure Rate | % of riders still unmatched after 5 minutes |

### 2. System Efficiency (Throughput Metrics)

| Metric | Description |
|--------|-------------|
| Clearance Rate | Passengers delivered per minute |
| Total Evacuation % | Progress toward clearing all riders |
| Dead Mileage Ratio | % of active driving time without a passenger |

### 3. Supply & Quality (Sustainability Metrics)

| Metric | Description |
|--------|-------------|
| Driver Utilization | Fraction of time occupied (ideal: 70-80%) |
| Braking Intensity | Count of hard-braking events (< -4.5 m/s²) |
| Effective Earnings/Hour | Simulated driver income ($15/trip base) |

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

The easiest way to run the simulation with the SUMO GUI and live Streamlit dashboard:

```bash
./run.sh --strategy baseline
```

This launches the SUMO GUI, runs the simulation, and opens a Streamlit dashboard at http://localhost:8501 with live three-panel KPI charts.

To compare all six strategies in parallel:

```bash
./run.sh --compare
```

### Scaling Up

Strategy parameters auto-scale with passenger count. Scale the simulation to larger events:

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
python main.py --strategy wave --wave-size 50
python main.py --strategy adaptive
python main.py --strategy surge_pricing --surge-threshold 2.0

# Compare all six strategies in parallel
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

The `./run.sh` script handles XQuartz setup automatically for single-strategy runs.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--strategy` | `baseline` | `baseline`, `leaky_bucket`, `virtual_queue`, `wave`, `adaptive`, or `surge_pricing` |
| `--gui` | off | Launch sumo-gui (requires XQuartz on macOS) |
| `--duration` | 7200 | Simulation duration in seconds |
| `--passengers` | 2000 | Number of riders in the burst |
| `--drivers` | 200 | Number of drivers in the fleet |
| `--bucket-size` | auto | Token bucket capacity (leaky bucket / adaptive) |
| `--leak-rate` | auto | Tokens per minute (leaky bucket) |
| `--num-slots` | auto | Number of time window slots (virtual queue) |
| `--slot-duration` | 120 | Seconds per slot (virtual queue) |
| `--wave-size` | auto | Drivers per wave (wave dispatch) |
| `--wave-threshold` | 0.8 | Completion fraction before next wave |
| `--adaptive-min-rate` | auto | Min tokens/min (adaptive) |
| `--adaptive-max-rate` | auto | Max tokens/min (adaptive) |
| `--surge-threshold` | 2.0 | Queue/idle ratio to trigger surge pricing |
| `--max-surge` | 5.0 | Maximum surge multiplier |
| `--output` | `output/` | Output directory for KPI CSVs and summaries |
| `--compare` | off | Run all strategies in parallel and compare |

Parameters marked **auto** scale proportionally with `--passengers` (relative to the 2,000 baseline).

## Output

Results are written to the `output/` directory:

- `kpi_<strategy>.csv` — Per-interval KPI snapshots with all metrics
- `summary.json` — Final simulation summary

Previous output is automatically cleared at the start of each run.

## Dashboard

The Streamlit dashboard (`dashboard.py`) provides live visualization organized into three panels: Rider Experience, System Efficiency, and Supply & Quality. When multiple strategy runs are present, it shows a **Comparison** tab with overlay charts and a summary table.

## Project Structure

```
├── agents/
│   ├── person.py          # Rider agent (states: waiting, matched, in_vehicle, delivered)
│   └── driver.py          # Driver agent (states: idle, en_route, occupied, returning)
├── dispatchers/
│   ├── base.py            # Abstract dispatcher interface
│   ├── baseline.py        # Naive immediate matching
│   ├── leaky_bucket.py    # Token bucket rate limiting
│   ├── virtual_queue.py   # Time-window slot assignment
│   ├── wave.py            # Coordinated wave dispatching
│   ├── adaptive.py        # Self-tuning rate limiting
│   └── surge_pricing.py   # Demand shaping via simulated pricing
├── kpi/
│   └── tracker.py         # KPI computation and CSV/JSON export
├── network/
│   └── build_network.py   # OSM download and SUMO network generation
├── config.py              # Simulation parameters and strategy enum
├── simulation.py          # Main traci simulation loop
├── dashboard.py           # Streamlit three-panel KPI dashboard
├── main.py                # CLI entry point with parallel comparison
└── run.sh                 # Launch simulation + GUI + dashboard together
```
