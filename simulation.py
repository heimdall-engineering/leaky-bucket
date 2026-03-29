"""TraCI controller: the main simulation step loop.

Manages person/vehicle lifecycle, dispatching, and KPI collection
through the SUMO Traffic Control Interface (traci).
"""

import logging
import random
from pathlib import Path

import traci

from agents.driver import Driver, DriverState
from agents.person import Rider, RiderState
from config import SimConfig, Strategy
from dispatchers.base import BaseDispatcher
from dispatchers.baseline import BaselineDispatcher
from dispatchers.leaky_bucket import LeakyBucketDispatcher
from dispatchers.virtual_queue import VirtualQueueDispatcher
from dispatchers.wave import WaveDispatcher
from dispatchers.adaptive import AdaptiveDispatcher
from dispatchers.surge_pricing import SurgePricingDispatcher
from kpi.tracker import KPITracker

logger = logging.getLogger(__name__)


class Simulation:
    """Orchestrates the SUMO simulation via traci."""

    def __init__(self, config: SimConfig):
        self.cfg = config
        self.riders: dict[str, Rider] = {}
        self.drivers: dict[str, Driver] = {}
        self.dispatcher: BaseDispatcher = self._create_dispatcher()
        self.kpi = KPITracker(
            output_dir=config.output_dir,
            strategy_name=self.dispatcher.name(),
            log_interval=config.kpi_log_interval,
        )
        self._edge_cache: list[str] = []
        self._pickup_edges: list[str] = []

    def _create_dispatcher(self) -> BaseDispatcher:
        if self.cfg.strategy == Strategy.BASELINE:
            return BaselineDispatcher()
        elif self.cfg.strategy == Strategy.LEAKY_BUCKET:
            return LeakyBucketDispatcher(
                bucket_size=self.cfg.bucket_size,
                leak_rate=self.cfg.leak_rate,
            )
        elif self.cfg.strategy == Strategy.VIRTUAL_QUEUE:
            return VirtualQueueDispatcher(
                slot_duration=self.cfg.slot_duration,
                num_slots=self.cfg.num_slots,
                incentive_discount=self.cfg.incentive_discount,
            )
        elif self.cfg.strategy == Strategy.WAVE:
            return WaveDispatcher(
                wave_size=self.cfg.wave_size,
                completion_threshold=self.cfg.wave_completion_threshold,
            )
        elif self.cfg.strategy == Strategy.ADAPTIVE:
            return AdaptiveDispatcher(
                base_rate=self.cfg.adaptive_base_rate,
                min_rate=self.cfg.adaptive_min_rate,
                max_rate=self.cfg.adaptive_max_rate,
                bucket_size=self.cfg.bucket_size,
                num_drivers=self.cfg.num_drivers,
            )
        elif self.cfg.strategy == Strategy.SURGE_PRICING:
            return SurgePricingDispatcher(
                surge_threshold=self.cfg.surge_threshold,
                max_surge=self.cfg.max_surge,
                defer_probability_base=self.cfg.surge_defer_probability,
            )
        raise ValueError(f"Unknown strategy: {self.cfg.strategy}")

    def start(self) -> None:
        """Start the SUMO simulation via traci."""
        sumo_binary = "sumo-gui" if self.cfg.gui else "sumo"
        sumo_cmd = [
            sumo_binary,
            "-c", self.cfg.sumo_cfg,
            "--step-length", str(self.cfg.step_length),
            "--no-step-log", "true",
        ]
        traci.start(sumo_cmd)
        logger.info("SUMO started with strategy: %s", self.dispatcher.name())

        # Cache network edges for random destination generation
        all_edges = traci.edge.getIDList()
        # Filter to edges that passenger vehicles can actually use
        self._edge_cache = []
        for e in all_edges:
            if e.startswith(":"):
                continue
            num_lanes = traci.edge.getLaneNumber(e)
            if num_lanes == 0:
                continue
            # Skip very short edges that cause departure position issues
            lane_length = traci.lane.getLength(f"{e}_0")
            if lane_length < 10.0:
                continue
            # Check if at least one lane allows passenger vehicles
            for i in range(num_lanes):
                allowed = traci.lane.getAllowed(f"{e}_{i}")
                # Empty allowed list means all vehicles allowed;
                # otherwise check for "passenger" class
                if not allowed or "passenger" in allowed:
                    self._edge_cache.append(e)
                    break
        logger.info("Network has %d passenger-accessible edges", len(self._edge_cache))

        # Filter to the largest connected component so all edges can reach each other
        self._edge_cache = self._largest_connected_component(self._edge_cache)
        logger.info("Largest connected component: %d edges", len(self._edge_cache))

        # Identify pickup-zone edges (near stadium center)
        self._pickup_edges = self._find_edges_near_center()
        if not self._pickup_edges:
            logger.warning("No edges found near stadium center, using first 10 edges")
            self._pickup_edges = self._edge_cache[:10]

    def _largest_connected_component(self, edges: list[str]) -> list[str]:
        """Keep only edges that can route to AND from a reference hub edge."""
        if not edges:
            return edges

        # Pick the hub: try several candidates near the center, use the one
        # that connects to the most edges
        candidates = random.sample(edges, min(10, len(edges)))
        best_hub = candidates[0]
        best_count = 0

        for candidate in candidates:
            count = 0
            test_targets = random.sample(edges, min(30, len(edges)))
            for target in test_targets:
                try:
                    r1 = traci.simulation.findRoute(candidate, target)
                    r2 = traci.simulation.findRoute(target, candidate)
                    if r1.edges and r2.edges:
                        count += 1
                except traci.TraCIException:
                    continue
            if count > best_count:
                best_count = count
                best_hub = candidate

        logger.info("Filtering edges for reachability using hub edge '%s'...", best_hub)

        # Keep only edges that can route to AND from the hub
        reachable = []
        for edge in edges:
            if edge == best_hub:
                reachable.append(edge)
                continue
            try:
                r1 = traci.simulation.findRoute(best_hub, edge)
                r2 = traci.simulation.findRoute(edge, best_hub)
                if r1.edges and r2.edges:
                    reachable.append(edge)
            except traci.TraCIException:
                continue

        return reachable

    def _find_edges_near_center(self) -> list[str]:
        """Find edges within pickup_radius of the network center."""
        # Use the network center as approximation for stadium location
        edges_with_pos = []
        for edge_id in self._edge_cache:
            try:
                # Get position via the first lane's shape
                lane_id = f"{edge_id}_0"
                shape = traci.lane.getShape(lane_id)
                if shape:
                    x, y = shape[0]
                    edges_with_pos.append((edge_id, x, y))
            except traci.TraCIException:
                continue

        if not edges_with_pos:
            return []

        # Compute centroid
        cx = sum(x for _, x, y in edges_with_pos) / len(edges_with_pos)
        cy = sum(y for _, x, y in edges_with_pos) / len(edges_with_pos)

        # Find edges near centroid
        near_edges = []
        for edge_id, x, y in edges_with_pos:
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if dist < self.cfg.pickup_radius:
                near_edges.append(edge_id)

        logger.info("Found %d edges within %.0fm of network center", len(near_edges), self.cfg.pickup_radius)
        return near_edges

    def _random_peripheral_edge(self) -> str:
        """Pick a random edge from the network periphery (destinations)."""
        # Exclude pickup zone edges to create trips away from the stadium
        peripheral = [e for e in self._edge_cache if e not in self._pickup_edges]
        if not peripheral:
            peripheral = self._edge_cache
        return random.choice(peripheral)

    def _random_pickup_edge(self) -> str:
        """Pick a random edge from the pickup zone."""
        return random.choice(self._pickup_edges)

    def _spawn_burst(self, step: int) -> None:
        """Spawn all person agents at the burst time."""
        if step != self.cfg.burst_time:
            return

        logger.info("Spawning %d riders at step %d", self.cfg.num_passengers, step)
        for i in range(self.cfg.num_passengers):
            person_id = f"rider_{i}"
            origin = self._random_pickup_edge()
            dest = self._random_peripheral_edge()

            rider = Rider(
                person_id=person_id,
                origin_edge=origin,
                dest_edge=dest,
                request_time=step,
            )
            self.riders[person_id] = rider

            # Add person to SUMO — they walk to the edge and wait
            try:
                lane_length = traci.lane.getLength(f"{origin}_0")
                max_pos = max(0.1, lane_length - 1.0)
                pos = random.uniform(0, max_pos)
                traci.person.add(person_id, origin, pos=pos)
                traci.person.appendWaitingStage(person_id, duration=self.cfg.sim_duration)
            except traci.TraCIException as e:
                logger.debug("Could not add person %s: %s", person_id, e)
                rider.state = RiderState.DELIVERED  # skip broken ones

    def _spawn_drivers(self) -> None:
        """Spawn the driver fleet at simulation start."""
        logger.info("Spawning %d drivers", self.cfg.num_drivers)
        for i in range(self.cfg.num_drivers):
            vehicle_id = f"driver_{i}"
            staging = self._random_peripheral_edge()  # start spread out

            driver = Driver(vehicle_id=vehicle_id, staging_edge=staging)
            self.drivers[vehicle_id] = driver

            try:
                lane_length = traci.lane.getLength(f"{staging}_0")
                # Vehicle length is 4.5m; need room for that on the edge
                max_pos = lane_length - 5.0
                if max_pos > 0.1:
                    dep_pos = str(random.uniform(0, max_pos))
                else:
                    dep_pos = "base"
                traci.vehicle.add(
                    vehicle_id,
                    routeID="",
                    typeID="uberx",
                    depart="now",
                    departPos=dep_pos,
                )
                # Set initial route: just park on the staging edge
                traci.vehicle.changeTarget(vehicle_id, staging)
            except traci.TraCIException as e:
                logger.debug("Could not add vehicle %s: %s", vehicle_id, e)

    def _update_driver_states(self, step: int) -> None:
        """Check traci state and update driver agents."""
        active_vehicles = set(traci.vehicle.getIDList())

        for vid, driver in self.drivers.items():
            driver.tick()

            if vid not in active_vehicles:
                continue

            if driver.state == DriverState.EN_ROUTE_TO_PICKUP:
                # Check if driver reached the pickup edge
                try:
                    current_edge = traci.vehicle.getRoadID(vid)
                    if current_edge == driver.pickup_edge:
                        driver.pickup()
                        rider = self.riders.get(driver.assigned_rider)
                        if rider:
                            rider.state = RiderState.IN_VEHICLE
                            rider.pickup_time = step
                            # Reroute driver to destination
                            try:
                                traci.vehicle.changeTarget(vid, driver.dest_edge)
                            except traci.TraCIException:
                                # Edge unreachable, complete trip immediately
                                self._complete_trip(driver, rider, step)
                except traci.TraCIException:
                    pass

            elif driver.state == DriverState.OCCUPIED:
                # Check if driver reached the destination
                try:
                    current_edge = traci.vehicle.getRoadID(vid)
                    if current_edge == driver.dest_edge:
                        rider = self.riders.get(driver.assigned_rider)
                        if rider:
                            self._complete_trip(driver, rider, step)
                except traci.TraCIException:
                    pass

            elif driver.state == DriverState.RETURNING_TO_STAGING:
                try:
                    current_edge = traci.vehicle.getRoadID(vid)
                    if current_edge == driver.staging_edge:
                        driver.arrive_staging()
                except traci.TraCIException:
                    # If we can't check, just mark idle
                    driver.arrive_staging()

    def _complete_trip(self, driver: Driver, rider: Rider, step: int) -> None:
        """Mark a trip as complete for both driver and rider."""
        rider.state = RiderState.DELIVERED
        rider.delivery_time = step
        driver.dropoff()

        # Remove person from simulation
        try:
            traci.person.remove(rider.person_id)
        except traci.TraCIException:
            pass

        # Reroute driver to staging
        try:
            traci.vehicle.changeTarget(driver.vehicle_id, driver.staging_edge)
        except traci.TraCIException:
            driver.arrive_staging()

    def _dispatch(self, step: int) -> None:
        """Run the dispatcher to match waiting riders with idle drivers."""
        waiting = [r for r in self.riders.values() if r.state == RiderState.WAITING]
        idle = [d for d in self.drivers.values() if d.state == DriverState.IDLE]

        if not waiting or not idle:
            return

        matches = self.dispatcher.step(step, waiting, idle)

        for rider, driver in matches:
            rider.state = RiderState.MATCHED
            rider.match_time = step
            rider.assigned_driver = driver.vehicle_id

            driver.dispatch_to(rider.person_id, rider.origin_edge, rider.dest_edge)

            # Reroute the vehicle toward the pickup edge
            try:
                current_edge = traci.vehicle.getRoadID(driver.vehicle_id)
                # Skip if vehicle is on an internal/junction edge (empty or starts with ":")
                if not current_edge or current_edge.startswith(":"):
                    # Undo match, retry next step
                    rider.state = RiderState.WAITING
                    rider.match_time = None
                    rider.assigned_driver = None
                    driver.arrive_staging()
                    continue
                traci.vehicle.changeTarget(driver.vehicle_id, rider.origin_edge)
            except traci.TraCIException:
                # Undo the match — put both back to available
                rider.state = RiderState.WAITING
                rider.match_time = None
                rider.assigned_driver = None
                driver.arrive_staging()

    def _measure_gridlock(self) -> float:
        """Compute average speed of vehicles within gridlock_radius of the stadium."""
        if not hasattr(self, '_stadium_center'):
            # Compute stadium center once from pickup edges
            positions = []
            for edge_id in self._pickup_edges:
                try:
                    lane_id = f"{edge_id}_0"
                    shape = traci.lane.getShape(lane_id)
                    if shape:
                        positions.append(shape[0])
                except traci.TraCIException:
                    continue
            if positions:
                self._stadium_center = (
                    sum(x for x, y in positions) / len(positions),
                    sum(y for x, y in positions) / len(positions),
                )
            else:
                self._stadium_center = None

        speeds = []
        radius = self.cfg.gridlock_radius
        for vid in traci.vehicle.getIDList():
            try:
                if self._stadium_center is not None:
                    vx, vy = traci.vehicle.getPosition(vid)
                    cx, cy = self._stadium_center
                    dist = ((vx - cx) ** 2 + (vy - cy) ** 2) ** 0.5
                    if dist > radius:
                        continue
                speed = traci.vehicle.getSpeed(vid)
                speeds.append(speed)
            except traci.TraCIException:
                continue
        return sum(speeds) / len(speeds) if speeds else 0.0

    def _count_hard_braking(self) -> int:
        """Count vehicles with acceleration below the hard-braking threshold."""
        count = 0
        for vid in traci.vehicle.getIDList():
            try:
                accel = traci.vehicle.getAcceleration(vid)
                if accel < self.cfg.hard_braking_threshold:
                    count += 1
            except traci.TraCIException:
                continue
        return count

    def _all_delivered(self) -> bool:
        """Check if all riders have been delivered."""
        if not self.riders:
            return False
        return all(r.state == RiderState.DELIVERED for r in self.riders.values())

    def run(self) -> None:
        """Execute the full simulation loop."""
        self.start()
        self._spawn_drivers()

        try:
            for step in range(self.cfg.sim_duration):
                traci.simulationStep()

                self._spawn_burst(step)
                self._update_driver_states(step)
                self._dispatch(step)

                # Track hard braking every step
                braking = self._count_hard_braking()
                self.kpi.record_hard_braking(braking)

                # Log KPIs at interval
                if step > 0 and step % self.cfg.kpi_log_interval == 0:
                    gridlock_speed = self._measure_gridlock()
                    self.kpi.compute_snapshot(step, self.riders, self.drivers, gridlock_speed)

                # Early termination if all riders delivered
                if step > self.cfg.burst_time + 100 and self._all_delivered():
                    logger.info("All riders delivered at step %d, ending simulation", step)
                    break

        except traci.TraCIException as e:
            logger.error("TraCI error at step %d: %s", step, e)
        finally:
            # Final KPI snapshot
            gridlock_speed = self._measure_gridlock()
            self.kpi.compute_snapshot(step, self.riders, self.drivers, gridlock_speed)
            self.kpi.close()
            traci.close()
            logger.info("Simulation complete.")
