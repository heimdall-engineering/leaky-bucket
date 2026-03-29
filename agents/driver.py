"""Driver agent with state machine for the simulation."""

from dataclasses import dataclass
from enum import Enum


class DriverState(Enum):
    IDLE = "idle"
    EN_ROUTE_TO_PICKUP = "en_route_to_pickup"
    OCCUPIED = "occupied"
    RETURNING_TO_STAGING = "returning_to_staging"


@dataclass
class Driver:
    vehicle_id: str
    staging_edge: str

    state: DriverState = DriverState.IDLE
    assigned_rider: str | None = None
    pickup_edge: str | None = None
    dest_edge: str | None = None

    # Tracking
    time_idle: int = 0
    time_occupied: int = 0
    time_en_route: int = 0  # time driving to pickup (dead mileage)
    time_returning: int = 0  # time returning to staging (dead mileage)
    trips_completed: int = 0
    total_steps: int = 0

    def tick(self) -> None:
        """Update time counters for one simulation step."""
        self.total_steps += 1
        if self.state == DriverState.IDLE:
            self.time_idle += 1
        elif self.state == DriverState.OCCUPIED:
            self.time_occupied += 1
        elif self.state == DriverState.EN_ROUTE_TO_PICKUP:
            self.time_en_route += 1
        elif self.state == DriverState.RETURNING_TO_STAGING:
            self.time_returning += 1

    @property
    def utilization(self) -> float:
        """Fraction of time spent occupied."""
        if self.total_steps == 0:
            return 0.0
        return self.time_occupied / self.total_steps

    @property
    def dead_mileage_ratio(self) -> float:
        """Fraction of active time spent without a passenger (en_route + returning)."""
        active = self.time_occupied + self.time_en_route + self.time_returning
        if active == 0:
            return 0.0
        return (self.time_en_route + self.time_returning) / active

    def dispatch_to(self, rider_id: str, pickup_edge: str, dest_edge: str) -> None:
        """Assign this driver to pick up a rider."""
        self.state = DriverState.EN_ROUTE_TO_PICKUP
        self.assigned_rider = rider_id
        self.pickup_edge = pickup_edge
        self.dest_edge = dest_edge

    def pickup(self) -> None:
        """Mark that the rider has been picked up."""
        self.state = DriverState.OCCUPIED

    def dropoff(self) -> None:
        """Mark trip completed, return to staging."""
        self.state = DriverState.RETURNING_TO_STAGING
        self.assigned_rider = None
        self.pickup_edge = None
        self.dest_edge = None
        self.trips_completed += 1

    def arrive_staging(self) -> None:
        """Arrived back at staging area, ready for next trip."""
        self.state = DriverState.IDLE
