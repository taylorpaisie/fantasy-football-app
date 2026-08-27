"""Future lineup-aware trade analysis contracts."""

from dataclasses import dataclass


@dataclass(slots=True)
class TradeImpact:
    before_weekly_points: float
    after_weekly_points: float
    rest_of_season_difference: float
    depth_notes: tuple[str, ...] = ()

