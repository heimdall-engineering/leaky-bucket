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

    Uses dispatch feedback from the simulation to track how many matches
    were actually accepted, avoiding deadlocks when the simulation rejects
    some matches.
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
        self._wave_active: bool = False
        self._actual_dispatched: int = 0  # set by notify_dispatch_result
        self._idle_after_dispatch: int = 0  # idle count right after wave sent

    def name(self) -> str:
        return f"Wave (size={self.wave_size}, threshold={self.completion_threshold:.0%})"

    def notify_dispatch_result(self, succeeded: int, failed: int) -> None:
        """Adjust wave tracking to reflect how many matches the simulation accepted."""
        self._actual_dispatched = succeeded
        # Correct idle-after-dispatch: failed matches mean those drivers stayed idle
        self._idle_after_dispatch += failed

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

        num_idle = len(idle_drivers)

        # Decide whether to release a new wave
        if self._wave_active:
            if self._actual_dispatched == 0:
                # No matches were actually accepted last wave — release immediately
                self._wave_active = False
            else:
                # Wave is complete when enough drivers have returned to idle
                returned = num_idle - self._idle_after_dispatch
                if returned < 0:
                    returned = 0
                wave_complete = returned >= self._actual_dispatched * self.completion_threshold
                if not wave_complete:
                    return []
                self._wave_active = False

        # Release a new wave
        self._wave_active = True
        # These will be corrected by notify_dispatch_result after _dispatch runs
        self._actual_dispatched = 0

        matches: list[tuple[Rider, Driver]] = []
        available = list(idle_drivers)
        remaining_queue: list[Rider] = []
        proposed = 0

        for rider in self.queue:
            if not available or proposed >= self.wave_size:
                remaining_queue.append(rider)
                continue
            driver = available.pop(0)
            matches.append((rider, driver))
            proposed += 1
            self.matches_made += 1

        self.queue = remaining_queue
        # Assume all dispatched; notify_dispatch_result will correct
        self._idle_after_dispatch = num_idle - proposed
        return matches
