"""Person (rider) agent for the simulation."""

from dataclasses import dataclass, field
from enum import Enum


class RiderState(Enum):
    WAITING = "waiting"
    MATCHED = "matched"
    IN_VEHICLE = "in_vehicle"
    DELIVERED = "delivered"


@dataclass
class Rider:
    person_id: str
    origin_edge: str
    dest_edge: str
    request_time: int  # simulation step when request was made

    state: RiderState = RiderState.WAITING
    assigned_driver: str | None = None
    match_time: int | None = None  # step when matched to a driver
    pickup_time: int | None = None  # step when picked up
    delivery_time: int | None = None  # step when delivered
    slot_index: int | None = None  # virtual queue slot assignment

    @property
    def wait_time(self) -> int | None:
        """Time from request to vehicle assignment (match), per spec."""
        if self.match_time is not None:
            return self.match_time - self.request_time
        return None

    @property
    def total_time(self) -> int | None:
        """Time from request to delivery."""
        if self.delivery_time is not None:
            return self.delivery_time - self.request_time
        return None
