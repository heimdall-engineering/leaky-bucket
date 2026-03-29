"""Wave Dispatching strategy.

Releases drivers in coordinated waves rather than a continuous stream.
A wave of N drivers is dispatched, then new matches are held until a
completion threshold of the current wave is reached.
"""

from agents.driver import Driver
from agents.person import Rider
from dispatchers.base import BaseDispatcher


class WaveDispatcher(BaseDispatcher):
    """Dispatches drivers in discrete waves to prevent sustained congestion.

    A wave of `wave_size` drivers is released at once. No new matches are
    made until `completion_threshold` fraction of the wave has completed
    (drivers returned to IDLE). Then the next wave is released.
    """

    def __init__(
        self,
        wave_size: int = 50,
        completion_threshold: float = 0.8,
    ):
        super().__init__()
        self.wave_size = wave_size
        self.completion_threshold = completion_threshold
        self.queue: list[Rider] = []
        self._wave_dispatched: int = 0  # how many sent in current wave
        self._wave_returned: int = 0  # how many came back idle
        self._prev_idle_ids: set[str] = set()  # track who was idle last step

    def name(self) -> str:
        return f"Wave (size={self.wave_size}, threshold={self.completion_threshold:.0%})"

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

        # Track wave completions: drivers that just became idle
        current_idle_ids = {d.vehicle_id for d in idle_drivers}
        newly_idle = current_idle_ids - self._prev_idle_ids
        self._wave_returned += len(newly_idle)
        self._prev_idle_ids = current_idle_ids

        # Decide whether to release a new wave
        wave_complete = (
            self._wave_dispatched == 0  # first wave
            or self._wave_dispatched <= self._wave_returned  # all returned
            or (
                self._wave_dispatched > 0
                and self._wave_returned >= self._wave_dispatched * self.completion_threshold
            )
        )

        if not wave_complete:
            return []

        # Release a new wave
        self._wave_dispatched = 0
        self._wave_returned = 0

        matches: list[tuple[Rider, Driver]] = []
        available = list(idle_drivers)
        remaining_queue: list[Rider] = []

        for rider in self.queue:
            if not available or self._wave_dispatched >= self.wave_size:
                remaining_queue.append(rider)
                continue
            driver = available.pop(0)
            matches.append((rider, driver))
            self._wave_dispatched += 1
            self.matches_made += 1

        self.queue = remaining_queue
        return matches
