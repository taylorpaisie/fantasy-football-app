"""Future injury/news impact contracts."""

from dataclasses import dataclass


@dataclass(slots=True)
class PlayerStatusEvent:
    player_id: str
    status: str
    source: str
    observed_at: str
    opportunity_impacts: tuple[str, ...] = ()

