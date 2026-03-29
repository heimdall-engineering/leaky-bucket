"""Surge Pricing (Demand Shaping) dispatcher.

Simulates dynamic pricing where a high queue length causes some riders
to defer their request. This naturally smooths demand over time.
"""

import random

from agents.driver import Driver
from agents.person import Rider, RiderState
from dispatchers.base import BaseDispatcher


class SurgePricingDispatcher(BaseDispatcher):
    """Demand-shaping dispatcher that simulates surge pricing.

    When the queue-to-driver ratio exceeds a threshold, a "surge multiplier"
    kicks in. Each step, riders in the queue have a probability of deferring
    (moving to the back of the queue / waiting longer) proportional to the
    surge level. This models riders who choose to wait for lower prices.

    Riders who don't defer are matched immediately to available drivers.
    """

    def __init__(
        self,
        surge_threshold: float = 2.0,
        max_surge: float = 5.0,
        defer_probability_base: float = 0.3,
    ):
        super().__init__()
        self.surge_threshold = surge_threshold  # queue/drivers ratio to trigger surge
        self.max_surge = max_surge  # cap on surge multiplier
        self.defer_probability_base = defer_probability_base  # base chance to defer at 1x surge
        self.queue: list[Rider] = []
        self._deferred: set[str] = set()  # riders currently deferring
        self._defer_until: dict[str, int] = {}  # rider_id -> step when deferral ends
        self.current_surge: float = 1.0

    def name(self) -> str:
        return f"Surge Pricing (threshold={self.surge_threshold}x, max={self.max_surge}x)"

    def _compute_surge(self, queue_len: int, num_idle: int, total_drivers: int) -> float:
        """Compute current surge multiplier."""
        if total_drivers == 0:
            return 1.0
        ratio = queue_len / max(1, num_idle)
        if ratio <= self.surge_threshold:
            return 1.0
        # Linear ramp from 1x to max_surge as ratio increases
        surge = 1.0 + (ratio - self.surge_threshold) * 0.5
        return min(surge, self.max_surge)

    def _defer_probability(self, surge: float) -> float:
        """Probability that a rider defers given the current surge level."""
        if surge <= 1.0:
            return 0.0
        # Higher surge -> more riders defer
        return min(0.9, self.defer_probability_base * (surge - 1.0))

    def step(
        self,
        current_step: int,
        waiting_riders: list[Rider],
        idle_drivers: list[Driver],
    ) -> list[tuple[Rider, Driver]]:
        # Add new waiting riders to queue (avoid duplicates)
        queued_ids = {r.person_id for r in self.queue}
        for rider in waiting_riders:
            if rider.person_id not in queued_ids:
                self.queue.append(rider)

        # Un-defer riders whose deferral period has ended
        for rider_id in list(self._defer_until.keys()):
            if current_step >= self._defer_until[rider_id]:
                self._deferred.discard(rider_id)
                del self._defer_until[rider_id]

        # Compute surge
        total_drivers = len(idle_drivers) + self.matches_made  # rough estimate
        self.current_surge = self._compute_surge(
            len(self.queue), len(idle_drivers), max(total_drivers, len(idle_drivers))
        )
        defer_prob = self._defer_probability(self.current_surge)

        # Process queue: riders may defer or get matched
        matches: list[tuple[Rider, Driver]] = []
        available = list(idle_drivers)
        remaining_queue: list[Rider] = []

        for rider in self.queue:
            if not available:
                remaining_queue.append(rider)
                continue

            # Skip riders currently deferring
            if rider.person_id in self._deferred:
                remaining_queue.append(rider)
                continue

            # Surge-based deferral: rider decides to wait for lower price
            if defer_prob > 0 and random.random() < defer_prob:
                self._deferred.add(rider.person_id)
                # Defer for 30-120 seconds depending on surge
                defer_time = int(30 + 90 * (self.current_surge / self.max_surge))
                self._defer_until[rider.person_id] = current_step + defer_time
                remaining_queue.append(rider)
                continue

            driver = available.pop(0)
            matches.append((rider, driver))
            self.matches_made += 1

        self.queue = remaining_queue
        return matches
