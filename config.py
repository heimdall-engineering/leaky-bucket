"""Simulation configuration and parameters."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Strategy(Enum):
    BASELINE = "baseline"
    LEAKY_BUCKET = "leaky_bucket"
    VIRTUAL_QUEUE = "virtual_queue"
    WAVE = "wave"
    ADAPTIVE = "adaptive"
    SURGE_PRICING = "surge_pricing"


@dataclass
class SimConfig:
    # Paths
    net_file: str = "network/stadium.net.xml"
    route_file: str = "network/stadium.rou.xml"
    sumo_cfg: str = "network/stadium.sumocfg"
    additional_files: str = "network/vehicle_types.xml"
    output_dir: str = "output"

    # Simulation
    sim_duration: int = 7200  # seconds (2 hours)
    step_length: float = 1.0  # seconds per step
    gui: bool = False

    # Demand (the burst)
    num_passengers: int = 2000
    burst_time: int = 0  # simulation step when passengers appear
    pickup_plaza_edge: str = "pickup_plaza"  # edge ID near stadium
    pickup_radius: float = 200.0  # meters from stadium center

    # Supply (the fleet)
    num_drivers: int = 200
    staging_area_edge: str = "staging_lot"

    # Stadium location (Levi's Stadium, Santa Clara - approximate center)
    stadium_lat: float = 37.4033
    stadium_lon: float = -121.9694
    map_radius_m: float = 2000  # meters around stadium to export

    # Leaky bucket parameters
    bucket_size: int = 30  # max active match tokens
    leak_rate: float = 10.0  # tokens released per minute

    # Virtual queue parameters
    slot_duration: int = 120  # seconds per window slot
    num_slots: int = 20
    incentive_discount: float = 0.15  # 15% cost reduction for later slots

    # Wave dispatch parameters
    wave_size: int = 50  # drivers per wave
    wave_completion_threshold: float = 0.8  # fraction of wave that must return before next

    # Adaptive rate limiting parameters
    adaptive_base_rate: float = 10.0  # tokens/min at 50% idle
    adaptive_min_rate: float = 2.0  # tokens/min floor
    adaptive_max_rate: float = 60.0  # tokens/min ceiling

    # Surge pricing parameters
    surge_threshold: float = 2.0  # queue/idle ratio to trigger surge
    max_surge: float = 5.0  # max surge multiplier
    surge_defer_probability: float = 0.3  # base deferral chance at 1x surge

    # KPI tracking
    kpi_log_interval: int = 100  # log every N steps
    gridlock_radius: float = 500.0  # meters from stadium for gridlock measurement
    hard_braking_threshold: float = -4.5  # m/s^2

    # Strategy
    strategy: Strategy = Strategy.BASELINE
