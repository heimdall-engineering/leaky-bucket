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
        self._blacklisted_edges: set[str] = set()

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
        candidate_edges = []
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
                if not allowed or "passenger" in allowed:
                    candidate_edges.append(e)
                    break
        logger.info("Network has %d passenger-accessible edges", len(candidate_edges))

        # Build verified edges anchored to the pickup zone
        self._pickup_edges, self._peripheral_edges, self._edge_cache = (
            self._build_verified_edges(candidate_edges)
        )
        logger.info(
            "Verified edges: %d pickup, %d peripheral, %d total",
            len(self._pickup_edges), len(self._peripheral_edges), len(self._edge_cache),
        )

    def _build_verified_edges(
        self, edges: list[str]
    ) -> tuple[list[str], list[str], list[str]]:
        """Build pickup and peripheral edge sets anchored to the pickup zone.

        Returns (pickup_edges, peripheral_edges, all_verified_edges).
        """
        if not edges:
            return [], [], []

        # --- Step 1: Find candidate pickup edges near the network centroid ---
        edges_with_pos: list[tuple[str, float, float]] = []
        for edge_id in edges:
            try:
                lane_id = f"{edge_id}_0"
                shape = traci.lane.getShape(lane_id)
                if shape:
                    x, y = shape[0]
                    edges_with_pos.append((edge_id, x, y))
            except traci.TraCIException:
                continue

        if not edges_with_pos:
            return [], [], []

        cx = sum(x for _, x, y in edges_with_pos) / len(edges_with_pos)
        cy = sum(y for _, x, y in edges_with_pos) / len(edges_with_pos)

        candidate_pickup = []
        for edge_id, x, y in edges_with_pos:
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if dist < self.cfg.pickup_radius:
                candidate_pickup.append(edge_id)

        if not candidate_pickup:
            logger.warning("No edges near centroid, using 10 random edges as pickup")
            candidate_pickup = [e for e, _, _ in edges_with_pos[:10]]

        logger.info(
            "Found %d candidate pickup edges within %.0fm of centroid",
            len(candidate_pickup), self.cfg.pickup_radius,
        )

        # --- Step 2: Pick an anchor from candidate pickup edges ---
        # Choose the anchor with the best connectivity to other pickup candidates
        anchor_candidates = random.sample(
            candidate_pickup, min(10, len(candidate_pickup))
        )
        best_anchor = anchor_candidates[0]
        best_score = 0
        for cand in anchor_candidates:
            score = 0
            for other in random.sample(
                candidate_pickup, min(20, len(candidate_pickup))
            ):
                if other == cand:
                    continue
                try:
                    r1 = traci.simulation.findRoute(cand, other)
                    r2 = traci.simulation.findRoute(other, cand)
                    if r1.edges and r2.edges:
                        score += 1
                except traci.TraCIException:
                    continue
            if score > best_score:
                best_score = score
                best_anchor = cand

        logger.info("Pickup anchor: '%s' (score %d)", best_anchor, best_score)

        # --- Step 3: Filter pickup edges — must route to AND from anchor ---
        pickup_edges = []
        for edge in candidate_pickup:
            if edge == best_anchor:
                pickup_edges.append(edge)
                continue
            try:
                r1 = traci.simulation.findRoute(best_anchor, edge)
                r2 = traci.simulation.findRoute(edge, best_anchor)
                if r1.edges and r2.edges:
                    pickup_edges.append(edge)
            except traci.TraCIException:
                continue

        logger.info(
            "Pickup zone: %d / %d edges mutually routable with anchor",
            len(pickup_edges), len(candidate_pickup),
        )

        if not pickup_edges:
            pickup_edges = [best_anchor]

        # --- Step 4: Filter peripheral edges — must route to AND from anchor ---
        pickup_set = set(pickup_edges)
        candidate_peripheral = [e for e in edges if e not in pickup_set]

        peripheral_edges = []
        for edge in candidate_peripheral:
            try:
                r1 = traci.simulation.findRoute(best_anchor, edge)
                r2 = traci.simulation.findRoute(edge, best_anchor)
                if r1.edges and r2.edges:
                    peripheral_edges.append(edge)
            except traci.TraCIException:
                continue

        logger.info(
            "Peripheral: %d / %d edges mutually routable with anchor",
            len(peripheral_edges), len(candidate_peripheral),
        )

        if not peripheral_edges:
            peripheral_edges = list(pickup_edges)

        all_verified = pickup_edges + peripheral_edges

        # --- Step 5: Log route-verification sample ---
        sample_pickup = random.sample(pickup_edges, min(10, len(pickup_edges)))
        sample_periph = random.sample(peripheral_edges, min(50, len(peripheral_edges)))
        success = 0
        total = 0
        for p in sample_pickup:
            for d in sample_periph:
                total += 1
                try:
                    r1 = traci.simulation.findRoute(p, d)
                    r2 = traci.simulation.findRoute(d, p)
                    if r1.edges and r2.edges:
                        success += 1
                except traci.TraCIException:
                    continue
        if total:
            logger.info(
                "Route verification: %d / %d pickup↔peripheral pairs succeed (%.0f%%)",
                success, total, 100 * success / total,
            )

        return pickup_edges, peripheral_edges, all_verified

    def _random_peripheral_edge(self) -> str:
        """Pick a random edge from the network periphery (destinations)."""
        return random.choice(self._peripheral_edges)

    def _random_pickup_edge(self) -> str:
        """Pick a random edge from the pickup zone."""
        return random.choice(self._pickup_edges)

    def _validate_route(self, from_edge: str, to_edge: str) -> bool:
        """Check if a route exists between two edges."""
        try:
            route = traci.simulation.findRoute(from_edge, to_edge)
            return bool(route.edges)
        except traci.TraCIException:
            return False

    def _spawn_burst(self, step: int) -> None:
        """Spawn all person agents at the burst time."""
        if step != self.cfg.burst_time:
            return

        logger.info("Spawning %d riders at step %d", self.cfg.num_passengers, step)
        spawned = 0
        for i in range(self.cfg.num_passengers):
            person_id = f"rider_{i}"

            # Try up to 3 origin/dest combos to find a valid route
            placed = False
            for _ in range(3):
                origin = self._random_pickup_edge()
                dest = self._random_peripheral_edge()
                if self._validate_route(origin, dest):
                    placed = True
                    break

            if not placed:
                # Skip this rider entirely
                continue

            rider = Rider(
                person_id=person_id,
                origin_edge=origin,
                dest_edge=dest,
                request_time=step,
            )
            self.riders[person_id] = rider

            try:
                lane_length = traci.lane.getLength(f"{origin}_0")
                max_pos = max(0.1, lane_length - 1.0)
                pos = random.uniform(0, max_pos)
                traci.person.add(person_id, origin, pos=pos)
                traci.person.appendWaitingStage(person_id, duration=self.cfg.sim_duration)
                spawned += 1
            except traci.TraCIException as e:
                logger.debug("Could not add person %s: %s", person_id, e)
                rider.state = RiderState.DELIVERED  # skip broken ones

        logger.info("Successfully spawned %d / %d riders", spawned, self.cfg.num_passengers)

    def _spawn_drivers(self) -> None:
        """Spawn the driver fleet on edges verified routable to pickup zone."""
        logger.info("Spawning %d drivers", self.cfg.num_drivers)
        spawned = 0
        for i in range(self.cfg.num_drivers):
            vehicle_id = f"driver_{i}"

            # Pick a peripheral edge that can route to at least one pickup edge
            staging = None
            for _ in range(5):
                candidate = self._random_peripheral_edge()
                pickup_target = random.choice(self._pickup_edges)
                if self._validate_route(candidate, pickup_target):
                    staging = candidate
                    break
            if staging is None:
                # Fall back to any peripheral edge
                staging = self._random_peripheral_edge()

            driver = Driver(vehicle_id=vehicle_id, staging_edge=staging)
            self.drivers[vehicle_id] = driver

            try:
                lane_length = traci.lane.getLength(f"{staging}_0")
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
                traci.vehicle.changeTarget(vehicle_id, staging)
                spawned += 1
            except traci.TraCIException as e:
                logger.debug("Could not add vehicle %s: %s", vehicle_id, e)

        logger.info("Successfully spawned %d / %d drivers", spawned, self.cfg.num_drivers)

    def _update_driver_states(self, step: int) -> None:
        """Check traci state and update driver agents."""
        active_vehicles = set(traci.vehicle.getIDList())

        for vid, driver in self.drivers.items():
            driver.tick()

            if vid not in active_vehicles:
                continue

            if driver.state == DriverState.EN_ROUTE_TO_PICKUP:
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
                                self._complete_trip(driver, rider, step)
                except traci.TraCIException:
                    pass

            elif driver.state == DriverState.OCCUPIED:
                try:
                    current_edge = traci.vehicle.getRoadID(vid)
                    if current_edge == driver.dest_edge:
                        rider = self.riders.get(driver.assigned_rider)
                        if rider:
                            self._complete_trip(driver, rider, step)
                except traci.TraCIException:
                    pass

            elif driver.state == DriverState.RETURNING_TO_STAGING:
                # Immediately mark idle — no need to route back to staging
                driver.arrive_staging()
                # Update staging edge to wherever the driver currently is
                try:
                    current_edge = traci.vehicle.getRoadID(vid)
                    if current_edge and not current_edge.startswith(":"):
                        driver.staging_edge = current_edge
                except traci.TraCIException:
                    pass

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

        # Driver goes idle immediately where they are (no return trip)
        driver.arrive_staging()
        try:
            current_edge = traci.vehicle.getRoadID(driver.vehicle_id)
            if current_edge and not current_edge.startswith(":"):
                driver.staging_edge = current_edge
        except traci.TraCIException:
            pass

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

            # Get driver's current edge
            try:
                current_edge = traci.vehicle.getRoadID(driver.vehicle_id)
            except traci.TraCIException:
                current_edge = ""

            # Skip if vehicle is on an internal/junction edge
            if not current_edge or current_edge.startswith(":"):
                self._undo_match(rider, driver)
                continue

            # Validate the full route chain: current -> pickup -> dest
            if not self._validate_route(current_edge, rider.origin_edge):
                self._blacklist_edge(rider.origin_edge)
                self._undo_match(rider, driver)
                continue

            if not self._validate_route(rider.origin_edge, rider.dest_edge):
                self._blacklist_edge(rider.dest_edge)
                self._undo_match(rider, driver)
                # Mark rider as failed — dest is unreachable
                rider.state = RiderState.DELIVERED
                try:
                    traci.person.remove(rider.person_id)
                except traci.TraCIException:
                    pass
                continue

            try:
                traci.vehicle.changeTarget(driver.vehicle_id, rider.origin_edge)
            except traci.TraCIException:
                self._blacklist_edge(rider.origin_edge)
                self._undo_match(rider, driver)

    def _undo_match(self, rider: Rider, driver: Driver) -> None:
        """Revert a failed match so both rider and driver are available again."""
        if rider.state != RiderState.DELIVERED:
            rider.state = RiderState.WAITING
        rider.match_time = None
        rider.assigned_driver = None
        driver.arrive_staging()

    def _blacklist_edge(self, edge_id: str) -> None:
        """Mark an edge as unreachable and remove it from caches."""
        if edge_id in self._blacklisted_edges:
            return
        self._blacklisted_edges.add(edge_id)
        self._edge_cache = [e for e in self._edge_cache if e != edge_id]
        self._pickup_edges = [e for e in self._pickup_edges if e != edge_id]
        self._peripheral_edges = [e for e in self._peripheral_edges if e != edge_id]
        logger.debug("Blacklisted edge %s (total blacklisted: %d)", edge_id, len(self._blacklisted_edges))

    def _measure_gridlock(self) -> float:
        """Compute average speed of vehicles within gridlock_radius of the stadium."""
        if not hasattr(self, '_stadium_center'):
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
            logger.info(
                "Simulation complete. Blacklisted %d edges during run.",
                len(self._blacklisted_edges),
            )
