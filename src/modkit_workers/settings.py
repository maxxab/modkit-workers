"""Pure request-shaping bounds only; runtime resource configuration is held."""

from dataclasses import dataclass

from .handlers import InvalidWorkerConfiguration


def _validate_bounds(limit: int, discovery_budget: int) -> None:
    if (
        type(limit) is not int
        or not 1 <= limit <= 256
        or type(discovery_budget) is not int
        or not limit <= discovery_budget <= 4096
    ):
        raise InvalidWorkerConfiguration("Invalid acquisition bounds")


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerSettings:
    acquire_limit: int
    discovery_budget: int

    def __post_init__(self) -> None:
        _validate_bounds(self.acquire_limit, self.discovery_budget)
