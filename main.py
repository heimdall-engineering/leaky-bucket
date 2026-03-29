#!/usr/bin/env python3
"""LeakyBucket — Burst Congestion Simulation Runner.

Usage:
    # Build the network first (requires SUMO/netconvert installed):
    python -m network.build_network

    # Run simulation with different strategies:
    python main.py --strategy baseline
    python main.py --strategy leaky_bucket --bucket-size 30 --leak-rate 10
    python main.py --strategy virtual_queue --num-slots 20
    python main.py --strategy wave --wave-size 50
    python main.py --strategy adaptive
    python main.py --strategy surge_pricing --surge-threshold 2.0
    python main.py --strategy baseline --gui    # with SUMO GUI

    # Compare all strategies:
    python main.py --compare
"""

import argparse
import logging
import multiprocessing
import sys
from pathlib import Path

from config import SimConfig, Strategy
from simulation import Simulation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("leaky_bucket")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LeakyBucket: Burst Congestion Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["baseline", "leaky_bucket", "virtual_queue", "wave", "adaptive", "surge_pricing"],
        default="baseline",
        help="Dispatch strategy to use (default: baseline)",
    )
    parser.add_argument("--gui", action="store_true", help="Launch sumo-gui")
    parser.add_argument("--duration", type=int, default=7200, help="Sim duration in seconds")
    parser.add_argument("--passengers", type=int, default=2000, help="Number of riders")
    parser.add_argument("--drivers", type=int, default=200, help="Number of drivers")

    # Leaky bucket params (defaults auto-scale with --passengers if not set)
    parser.add_argument("--bucket-size", type=int, default=None, help="Token bucket capacity (default: scales with passengers)")
    parser.add_argument("--leak-rate", type=float, default=None, help="Tokens per minute (default: scales with passengers)")

    # Virtual queue params (defaults auto-scale with --passengers if not set)
    parser.add_argument("--num-slots", type=int, default=None, help="Number of time window slots (default: scales with passengers)")
    parser.add_argument("--slot-duration", type=int, default=None, help="Seconds per slot (default: auto)")

    # Wave dispatch params
    parser.add_argument("--wave-size", type=int, default=None, help="Drivers per wave (default: scales with passengers)")
    parser.add_argument("--wave-threshold", type=float, default=0.8, help="Completion fraction before next wave")

    # Adaptive rate params
    parser.add_argument("--adaptive-min-rate", type=float, default=None, help="Min tokens/min (default: scales with passengers)")
    parser.add_argument("--adaptive-max-rate", type=float, default=None, help="Max tokens/min (default: scales with passengers)")

    # Surge pricing params
    parser.add_argument("--surge-threshold", type=float, default=2.0, help="Queue/idle ratio to trigger surge")
    parser.add_argument("--max-surge", type=float, default=5.0, help="Max surge multiplier")

    # Output
    parser.add_argument("--output", type=str, default="output", help="Output directory")

    # Comparison mode
    parser.add_argument("--compare", action="store_true", help="Run all strategies and compare")

    # Network building
    parser.add_argument("--build-network", action="store_true", help="Build network from OSM before running")

    return parser.parse_args()


def run_single(config: SimConfig) -> None:
    """Run a single simulation with the given config."""
    sim = Simulation(config)
    sim.run()


def _run_strategy(args: tuple[Strategy, SimConfig]) -> None:
    """Run a single strategy in its own process (for parallel comparison)."""
    strategy, base_config = args
    # Re-init logging in child process
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{strategy.value}] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    config = SimConfig(
        net_file=base_config.net_file,
        route_file=base_config.route_file,
        sumo_cfg=base_config.sumo_cfg,
        additional_files=base_config.additional_files,
        output_dir=f"{base_config.output_dir}/{strategy.value}",
        sim_duration=base_config.sim_duration,
        gui=False,  # no GUI in parallel mode
        num_passengers=base_config.num_passengers,
        num_drivers=base_config.num_drivers,
        strategy=strategy,
        bucket_size=base_config.bucket_size,
        leak_rate=base_config.leak_rate,
        slot_duration=base_config.slot_duration,
        num_slots=base_config.num_slots,
        wave_size=base_config.wave_size,
        wave_completion_threshold=base_config.wave_completion_threshold,
        adaptive_base_rate=base_config.adaptive_base_rate,
        adaptive_min_rate=base_config.adaptive_min_rate,
        adaptive_max_rate=base_config.adaptive_max_rate,
        surge_threshold=base_config.surge_threshold,
        max_surge=base_config.max_surge,
        surge_defer_probability=base_config.surge_defer_probability,
    )
    run_single(config)


def run_comparison(base_config: SimConfig) -> None:
    """Run all strategies in parallel and produce comparison output."""
    strategies = list(Strategy)

    logger.info("Running %d strategies in parallel...", len(strategies))
    tasks = [(s, base_config) for s in strategies]

    with multiprocessing.Pool(processes=len(strategies)) as pool:
        pool.map(_run_strategy, tasks)

    logger.info("Comparison complete. Results in %s/*/", base_config.output_dir)


def main() -> None:
    args = parse_args()

    # Optionally build network first
    if args.build_network:
        from network.build_network import build
        build()

    # Clear previous output
    import shutil
    output_path = Path(args.output)
    if output_path.exists():
        shutil.rmtree(output_path)
        logger.info("Cleared previous output in %s/", args.output)

    # Auto-scale strategy parameters based on passenger count
    scale = args.passengers / 2000.0  # ratio vs. default 2000 passengers

    bucket_size = args.bucket_size if args.bucket_size is not None else max(30, int(30 * scale))
    leak_rate = args.leak_rate if args.leak_rate is not None else max(10.0, 10.0 * scale)
    slot_duration = args.slot_duration if args.slot_duration is not None else 120
    # Cap num_slots so all slots fit within the sim duration
    max_slots = max(1, args.duration // slot_duration)
    num_slots = args.num_slots if args.num_slots is not None else min(max_slots, max(20, int(20 * scale)))
    # Wave size should be a fraction of driver count, not passenger count
    wave_size = args.wave_size if args.wave_size is not None else max(50, args.drivers // 4)
    adaptive_min = args.adaptive_min_rate if args.adaptive_min_rate is not None else max(2.0, 2.0 * scale)
    adaptive_max = args.adaptive_max_rate if args.adaptive_max_rate is not None else max(60.0, 60.0 * scale)

    if scale > 1.0:
        logger.info(
            "Auto-scaled params for %d passengers (%.0fx): "
            "bucket_size=%d, leak_rate=%.0f/min, num_slots=%d, wave_size=%d, "
            "adaptive_rate=%.0f-%.0f/min",
            args.passengers, scale, bucket_size, leak_rate, num_slots,
            wave_size, adaptive_min, adaptive_max,
        )

    config = SimConfig(
        strategy=Strategy(args.strategy),
        gui=args.gui,
        sim_duration=args.duration,
        num_passengers=args.passengers,
        num_drivers=args.drivers,
        bucket_size=bucket_size,
        leak_rate=leak_rate,
        num_slots=num_slots,
        slot_duration=slot_duration,
        wave_size=wave_size,
        wave_completion_threshold=args.wave_threshold,
        adaptive_base_rate=(adaptive_min + adaptive_max) / 2,
        adaptive_min_rate=adaptive_min,
        adaptive_max_rate=adaptive_max,
        surge_threshold=args.surge_threshold,
        max_surge=args.max_surge,
        output_dir=args.output,
    )

    # Verify network files exist
    if not Path(config.sumo_cfg).exists():
        logger.error(
            "SUMO config not found at %s. Run with --build-network first, "
            "or run: python -m network.build_network",
            config.sumo_cfg,
        )
        sys.exit(1)

    if args.compare:
        run_comparison(config)
    else:
        run_single(config)


if __name__ == "__main__":
    main()
