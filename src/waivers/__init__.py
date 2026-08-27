"""Future waiver analysis contracts."""

from dataclasses import dataclass


@dataclass(slots=True)
class WaiverMove:
    add_player_id: str
    drop_player_id: str | None
    rest_of_season_gain: float | None = None
    weekly_starter_gain: float | None = None

