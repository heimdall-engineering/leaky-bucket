"""Adaptive Rate Limiting dispatcher.

Like Leaky Bucket, but the rate self-tunes based on current system load.
When many drivers are idle, the rate increases. When most are busy,
it throttles down to prevent congestion.
"""

from agents.driver import Driver
from agents.person import Rider
from dispatchers.base import BaseDispatcher


class AdaptiveDispatcher(BaseDispatcher):
    """Rate-limited dispatcher that adapts to system congestion.

    Maintains a token bucket like LeakyBucket, but the refill rate
    varies dynamically:
      - High idle ratio -> refill faster (up to max_rate)
      - Low idle ratio  -> refill slower (down to min_rate)

    This prevents flooding when the network is congested while
    maximizing throughput when roads are clear.
    """

    def __init__(
        self,
        base_rate: float = 10.0,
        min_rate: float = 2.0,
        max_rate: float = 60.0,
        bucket_size: int = 30,
        num_drivers: int = 200,
    ):
        super().__init__()
        self.base_rate = base_rate  # tokens per minute at 50% idle
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.bucket_size = bucket_size
        self.num_drivers = num_drivers
        self._tokens: float = bucket_size  # start full
        self._current_rate: float = base_rate
        self.queue: list[Rider] = []

    def name(self) -> str:
        return f"Adaptive (rate={self.min_rate}-{self.max_rate}/min)"

    def _compute_rate(self, num_idle: int) -> float:
        """Compute the current token refill rate based on idle driver ratio."""
        idle_ratio = num_idle / max(1, self.num_drivers)
        # Linear interpolation: 0% idle -> min_rate, 100% idle -> max_rate
        rate = self.min_rate + (self.max_rate - self.min_rate) * idle_ratio
        return rate

    def step(
        self,
        current_step: int,
        waiting_riders: list[Rider],
        idle_drivers: list[Driver],
    ) -> list[tuple[Rider, Driver]]:
        # Adapt rate based on current idle drivers
        self._current_rate = self._compute_rate(len(idle_drivers))

        # Refill tokens at the adaptive rate
        tokens_per_step = self._current_rate / 60.0
        self._tokens = min(self.bucket_size, self._tokens + tokens_per_step)

        # Add new waiting riders to queue (avoid duplicates)
        queued_ids = {r.person_id for r in self.queue}
        for rider in waiting_riders:
            if rider.person_id not in queued_ids:
                self.queue.append(rider)

        # Drain queue at the token rate
        matches: list[tuple[Rider, Driver]] = []
        available = list(idle_drivers)
        remaining_queue: list[Rider] = []

        for rider in self.queue:
            if not available:
                remaining_queue.append(rider)
                continue
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                driver = available.pop(0)
                matches.append((rider, driver))
                self.matches_made += 1
            else:
                remaining_queue.append(rider)

        self.queue = remaining_queue
        return matches
