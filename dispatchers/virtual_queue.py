"""Virtual Queuing (incentivized smoothing) dispatcher."""

import random

from agents.driver import Driver
from agents.person import Rider, RiderState
from dispatchers.base import BaseDispatcher


class VirtualQueueDispatcher(BaseDispatcher):
    """Assigns riders to time-window slots to smooth demand.

    Riders are distributed across slots. Those who accept a later slot
    get a priority boost (simulating a fare discount). Dispatching only
    happens when the current simulation time falls within a rider's slot.
    """

    def __init__(
        self,
        slot_duration: int = 120,
        num_slots: int = 20,
        incentive_discount: float = 0.15,
        acceptance_probability: float = 0.6,
    ):
        super().__init__()
        self.slot_duration = slot_duration
        self.num_slots = num_slots
        self.incentive_discount = incentive_discount
        self.acceptance_probability = acceptance_probability

        # slot_index -> list of riders assigned to that slot
        self.slots: dict[int, list[Rider]] = {i: [] for i in range(num_slots)}
        self._assigned: set[str] = set()

    def name(self) -> str:
        return f"Virtual Queue ({self.num_slots} slots x {self.slot_duration}s)"

    def _assign_slot(self, rider: Rider, current_step: int) -> None:
        """Assign a rider to a slot. Some riders accept a later slot."""
        current_slot = current_step // self.slot_duration
        preferred_slot = max(0, min(current_slot, self.num_slots - 1))

        # Simulate whether rider accepts a later (incentivized) slot
        if random.random() < self.acceptance_probability:
            # Accept a later slot (1-3 slots ahead)
            offset = random.randint(1, 3)
            assigned = min(preferred_slot + offset, self.num_slots - 1)
        else:
            assigned = preferred_slot

        rider.slot_index = assigned
        self.slots[assigned].append(rider)
        self._assigned.add(rider.person_id)

    def step(
        self,
        current_step: int,
        waiting_riders: list[Rider],
        idle_drivers: list[Driver],
    ) -> list[tuple[Rider, Driver]]:
        # Assign unassigned riders to slots
        for rider in waiting_riders:
            if rider.person_id not in self._assigned:
                self._assign_slot(rider, current_step)

        # Determine the active slot for the current time
        active_slot = current_step // self.slot_duration
        if active_slot >= self.num_slots:
            active_slot = self.num_slots - 1

        # Dispatch riders from the active slot (and any overdue earlier slots)
        matches: list[tuple[Rider, Driver]] = []
        available = list(idle_drivers)

        for slot_idx in range(active_slot + 1):
            remaining: list[Rider] = []
            for rider in self.slots[slot_idx]:
                if not available:
                    remaining.append(rider)
                    continue
                if rider.state == RiderState.WAITING:
                    driver = available.pop(0)
                    matches.append((rider, driver))
                    self.matches_made += 1
                # Already matched/picked up riders are dropped from the slot
            self.slots[slot_idx] = remaining

        return matches
