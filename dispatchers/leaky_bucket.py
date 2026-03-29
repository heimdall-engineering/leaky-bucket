"""Leaky Bucket (rate-limiting) dispatcher."""

from agents.driver import Driver
from agents.person import Rider
from dispatchers.base import BaseDispatcher


class TokenBucket:
    """Classic token-bucket rate limiter.

    Tokens accumulate at `leak_rate` per minute (i.e. per 60 simulation steps).
    At most `bucket_size` tokens can be stored. Each match consumes one token.
    """

    def __init__(self, bucket_size: int, leak_rate: float, step_length: float = 1.0):
        self.bucket_size = bucket_size
        self.leak_rate = leak_rate  # tokens per minute
        self._tokens: float = bucket_size  # start full
        self._tokens_per_step = (leak_rate / 60.0) * step_length

    def refill(self) -> None:
        """Add tokens for one simulation step."""
        self._tokens = min(self.bucket_size, self._tokens + self._tokens_per_step)

    def try_consume(self) -> bool:
        """Attempt to consume one token. Returns True if successful."""
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    @property
    def available_tokens(self) -> int:
        return int(self._tokens)


class LeakyBucketDispatcher(BaseDispatcher):
    """Rate-limited dispatcher using a token bucket.

    Requests enter a FIFO queue. Each simulation step, the bucket refills
    at the configured leak rate. Matches are only made when a token is
    available, preventing a swarm of vehicles from flooding the pickup zone.
    """

    def __init__(self, bucket_size: int = 30, leak_rate: float = 10.0):
        super().__init__()
        self.bucket = TokenBucket(bucket_size, leak_rate)
        self.queue: list[Rider] = []

    def name(self) -> str:
        return f"Leaky Bucket (B={self.bucket.bucket_size}, R={self.bucket.leak_rate}/min)"

    def step(
        self,
        current_step: int,
        waiting_riders: list[Rider],
        idle_drivers: list[Driver],
    ) -> list[tuple[Rider, Driver]]:
        # Refill tokens for this step
        self.bucket.refill()

        # Add new waiting riders to the back of the queue (avoid duplicates)
        queued_ids = {r.person_id for r in self.queue}
        for rider in waiting_riders:
            if rider.person_id not in queued_ids:
                self.queue.append(rider)

        matches: list[tuple[Rider, Driver]] = []
        available = list(idle_drivers)

        # Drain queue at the token rate
        remaining_queue: list[Rider] = []
        for rider in self.queue:
            if not available:
                remaining_queue.append(rider)
                continue
            if self.bucket.try_consume():
                driver = available.pop(0)
                matches.append((rider, driver))
                self.matches_made += 1
            else:
                remaining_queue.append(rider)

        self.queue = remaining_queue
        return matches
