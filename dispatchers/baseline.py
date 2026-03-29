"""Baseline (naive) dispatcher: immediate nearest-driver matching."""

from agents.driver import Driver
from agents.person import Rider
from dispatchers.base import BaseDispatcher


class BaselineDispatcher(BaseDispatcher):
    """Immediately match every waiting rider to the nearest idle driver.

    No throttling or queuing — all available drivers are dispatched at once.
    This is the control strategy that produces maximum initial throughput
    but risks gridlock around the pickup zone.
    """

    def name(self) -> str:
        return "Baseline (Naive)"

    def step(
        self,
        current_step: int,
        waiting_riders: list[Rider],
        idle_drivers: list[Driver],
    ) -> list[tuple[Rider, Driver]]:
        matches: list[tuple[Rider, Driver]] = []
        available = list(idle_drivers)

        for rider in waiting_riders:
            if not available:
                break
            # Pick first available driver (in a real system, pick nearest;
            # here driver ordering serves as a proxy for proximity)
            driver = available.pop(0)
            matches.append((rider, driver))
            self.matches_made += 1

        return matches
