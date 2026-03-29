"""Abstract base class for dispatch strategies."""

from abc import ABC, abstractmethod

from agents.driver import Driver
from agents.person import Rider


class BaseDispatcher(ABC):
    """Base dispatcher that all strategies inherit from.

    A dispatcher decides *when* and *how* to match waiting riders
    to idle drivers. Subclasses implement the matching policy.
    """

    def __init__(self) -> None:
        self.matches_made: int = 0

    @abstractmethod
    def step(
        self,
        current_step: int,
        waiting_riders: list[Rider],
        idle_drivers: list[Driver],
    ) -> list[tuple[Rider, Driver]]:
        """Run one dispatch cycle and return (rider, driver) pairs to match.

        Args:
            current_step: Current simulation time step.
            waiting_riders: Riders in WAITING state.
            idle_drivers: Drivers in IDLE state.

        Returns:
            List of (rider, driver) tuples to dispatch this step.
        """
        ...

    def notify_dispatch_result(self, succeeded: int, failed: int) -> None:
        """Called by _dispatch after processing matches.

        Subclasses can override to adjust internal state based on how many
        matches were actually accepted vs rejected by the simulation.
        """

    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name."""
        ...
