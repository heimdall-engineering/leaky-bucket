"""KPI tracking, computation, and CSV logging."""

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from agents.driver import Driver
from agents.person import Rider

logger = logging.getLogger(__name__)


@dataclass
class KPISnapshot:
    """A single snapshot of all KPIs at a given simulation step."""
    step: int

    # Panel 1: Rider Experience
    avg_wait_time: float
    p95_wait_time: float
    avg_etr: float  # estimated time to request (time in queue before match)
    match_failure_rate: float  # % of riders still unmatched after threshold

    # Panel 2: System Efficiency
    clearance_rate: float  # deliveries per minute
    total_evacuation_pct: float  # % of riders cleared so far
    dead_mileage_ratio: float  # fraction of active driving without passenger

    # Panel 3: Supply & Quality
    driver_utilization: float
    braking_intensity: int  # hard-braking events this interval
    effective_eph: float  # simulated earnings per hour

    # Status counts
    riders_waiting: int
    riders_matched: int
    riders_in_vehicle: int
    riders_delivered: int
    riders_total: int
    drivers_idle: int
    drivers_en_route: int
    drivers_occupied: int
    drivers_returning: int


CSV_COLUMNS = [
    "step",
    "avg_wait_time", "p95_wait_time", "avg_etr", "match_failure_rate",
    "clearance_rate", "total_evacuation_pct", "dead_mileage_ratio",
    "driver_utilization", "braking_intensity", "effective_eph",
    "riders_waiting", "riders_matched", "riders_in_vehicle", "riders_delivered",
    "riders_total",
    "drivers_idle", "drivers_en_route", "drivers_occupied", "drivers_returning",
]


class KPITracker:
    """Collects, computes, and logs simulation KPIs."""

    # Simulated base fare for EPH calculation
    BASE_FARE_PER_TRIP = 15.0  # dollars

    def __init__(self, output_dir: str, strategy_name: str, log_interval: int = 100):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.strategy_name = strategy_name
        self.log_interval = log_interval

        self.snapshots: list[KPISnapshot] = []
        self.hard_braking_count: int = 0
        self._last_total_deliveries: int = 0
        self._interval_braking: int = 0

        # CSV setup
        safe_name = strategy_name.replace(" ", "_").replace("/", "-")
        self.csv_path = self.output_dir / f"kpi_{safe_name}.csv"
        self._csv_file = open(self.csv_path, "w", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(CSV_COLUMNS)

    def record_hard_braking(self, count: int) -> None:
        """Record hard-braking events detected this step."""
        self.hard_braking_count += count
        self._interval_braking += count

    def compute_snapshot(
        self,
        step: int,
        riders: dict[str, Rider],
        drivers: dict[str, Driver],
        gridlock_speed: float,
    ) -> KPISnapshot:
        """Compute a KPI snapshot from current rider/driver states."""
        from agents.person import RiderState
        from agents.driver import DriverState

        riders_total = len(riders)

        # --- Panel 1: Rider Experience ---
        wait_times = []  # all riders (including still-waiting)
        served_wait_times = []  # only riders who were matched/picked-up/delivered
        for r in riders.values():
            if r.wait_time is not None:
                wait_times.append(r.wait_time)
                served_wait_times.append(r.wait_time)
            elif r.state == RiderState.WAITING:
                elapsed = step - r.request_time
                wait_times.append(elapsed)

        avg_wait = float(np.mean(wait_times)) if wait_times else 0.0
        # P95 over served riders only — otherwise it's always pegged at sim duration
        p95_wait = float(np.percentile(served_wait_times, 95)) if served_wait_times else 0.0
        avg_etr = float(np.mean(wait_times)) if wait_times else 0.0

        # Match failure rate: riders still waiting after 5 minutes (300 steps)
        match_failure_threshold = 300
        riders_waiting = sum(1 for r in riders.values() if r.state == RiderState.WAITING)
        long_waiters = sum(
            1 for r in riders.values()
            if r.state == RiderState.WAITING and (step - r.request_time) > match_failure_threshold
        )
        match_failure_rate = (long_waiters / riders_total * 100) if riders_total > 0 else 0.0

        # --- Panel 2: System Efficiency ---
        total_delivered = sum(1 for r in riders.values() if r.state == RiderState.DELIVERED)
        interval_deliveries = total_delivered - self._last_total_deliveries
        self._last_total_deliveries = total_delivered
        # Deliveries per minute (log_interval steps = log_interval seconds at 1s/step)
        clearance_rate = (interval_deliveries / self.log_interval) * 60.0

        total_evacuation_pct = (total_delivered / riders_total * 100) if riders_total > 0 else 0.0

        # Dead mileage: average across all drivers
        dead_ratios = [d.dead_mileage_ratio for d in drivers.values()]
        dead_mileage_ratio = float(np.mean(dead_ratios)) if dead_ratios else 0.0

        # --- Panel 3: Supply & Quality ---
        util_values = [d.utilization for d in drivers.values()]
        avg_util = float(np.mean(util_values)) if util_values else 0.0

        # Effective earnings per hour: trips_completed * fare / hours_online
        total_trips = sum(d.trips_completed for d in drivers.values())
        total_driver_hours = sum(d.total_steps for d in drivers.values()) / 3600.0
        effective_eph = (total_trips * self.BASE_FARE_PER_TRIP / total_driver_hours) if total_driver_hours > 0 else 0.0

        # Status counts
        riders_matched = sum(1 for r in riders.values() if r.state == RiderState.MATCHED)
        riders_in_vehicle = sum(1 for r in riders.values() if r.state == RiderState.IN_VEHICLE)
        drivers_idle = sum(1 for d in drivers.values() if d.state == DriverState.IDLE)
        drivers_en_route = sum(1 for d in drivers.values() if d.state == DriverState.EN_ROUTE_TO_PICKUP)
        drivers_occupied = sum(1 for d in drivers.values() if d.state == DriverState.OCCUPIED)
        drivers_returning = sum(1 for d in drivers.values() if d.state == DriverState.RETURNING_TO_STAGING)

        snapshot = KPISnapshot(
            step=step,
            avg_wait_time=avg_wait,
            p95_wait_time=p95_wait,
            avg_etr=avg_etr,
            match_failure_rate=match_failure_rate,
            clearance_rate=clearance_rate,
            total_evacuation_pct=total_evacuation_pct,
            dead_mileage_ratio=dead_mileage_ratio,
            driver_utilization=avg_util,
            braking_intensity=self._interval_braking,
            effective_eph=effective_eph,
            riders_waiting=riders_waiting,
            riders_matched=riders_matched,
            riders_in_vehicle=riders_in_vehicle,
            riders_delivered=total_delivered,
            riders_total=riders_total,
            drivers_idle=drivers_idle,
            drivers_en_route=drivers_en_route,
            drivers_occupied=drivers_occupied,
            drivers_returning=drivers_returning,
        )

        self._interval_braking = 0
        self.snapshots.append(snapshot)
        self._write_csv_row(snapshot)

        logger.info(
            "Step %d | AWT=%.0fs P95=%.0fs ETR=%.0fs Fail=%.1f%% | "
            "CR=%.1f/min Evac=%.1f%% Dead=%.0f%% | "
            "Util=%.1f%% EPH=$%.0f Brake=%d | "
            "W=%d M=%d V=%d D=%d",
            step, avg_wait, p95_wait, avg_etr, match_failure_rate,
            clearance_rate, total_evacuation_pct, dead_mileage_ratio * 100,
            avg_util * 100, effective_eph, self._interval_braking,
            riders_waiting, riders_matched, riders_in_vehicle, total_delivered,
        )

        return snapshot

    def _write_csv_row(self, s: KPISnapshot) -> None:
        self._csv_writer.writerow([
            s.step,
            f"{s.avg_wait_time:.1f}", f"{s.p95_wait_time:.1f}",
            f"{s.avg_etr:.1f}", f"{s.match_failure_rate:.2f}",
            f"{s.clearance_rate:.2f}", f"{s.total_evacuation_pct:.2f}",
            f"{s.dead_mileage_ratio:.4f}",
            f"{s.driver_utilization:.4f}", s.braking_intensity,
            f"{s.effective_eph:.2f}",
            s.riders_waiting, s.riders_matched, s.riders_in_vehicle,
            s.riders_delivered, s.riders_total,
            s.drivers_idle, s.drivers_en_route, s.drivers_occupied,
            s.drivers_returning,
        ])
        self._csv_file.flush()

    def write_summary(self) -> None:
        """Write a JSON summary of the entire simulation run."""
        if not self.snapshots:
            return

        last = self.snapshots[-1]
        summary = {
            "strategy": self.strategy_name,
            "total_steps": last.step,
            "riders_total": last.riders_total,
            "riders_delivered": last.riders_delivered,
            "total_evacuation_pct": last.total_evacuation_pct,
            "final_avg_wait_time": last.avg_wait_time,
            "final_p95_wait_time": last.p95_wait_time,
            "final_match_failure_rate": last.match_failure_rate,
            "final_dead_mileage_ratio": last.dead_mileage_ratio,
            "final_driver_utilization": last.driver_utilization,
            "final_effective_eph": last.effective_eph,
            "total_hard_braking": self.hard_braking_count,
        }

        summary_path = self.output_dir / "summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info("Summary written to %s", summary_path)

    def close(self) -> None:
        self.write_summary()
        self._csv_file.close()
