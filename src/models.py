"""Normalized application models independent of ESPN or Streamlit."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


PLAYER_COLUMNS = [
    "player_id",
    "espn_player_id",
    "player_name",
    "position",
    "team",
    "bye_week",
    "injury_status",
    "espn_rank",
    "ownership_pct",
    "projected_points",
    "actual_points",
    "adp",
    "consensus_rank",
    "model_rank",
    "position_rank",
    "tier",
    "drafted",
]


@dataclass(slots=True)
class LeagueInfo:
    league_id: int | None = None
    name: str = "Offline Fantasy League"
    season: int = 2026
    platform: str = "ESPN Fantasy Football"
    team_count: int = 16
    scoring_type: str = "standard"
    roster_slots: dict[str, int] = field(default_factory=dict)
    draft_type: str = "snake"
    draft_rounds: int = 15
    current_week: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LeagueSnapshot:
    league: LeagueInfo
    teams: pd.DataFrame = field(default_factory=pd.DataFrame)
    rosters: pd.DataFrame = field(default_factory=pd.DataFrame)
    players: pd.DataFrame = field(default_factory=pd.DataFrame)
    draft_picks: pd.DataFrame = field(default_factory=pd.DataFrame)
    matchups: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)


def ensure_player_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with every normalized player column present."""
    result = frame.copy()
    for column in PLAYER_COLUMNS:
        if column not in result.columns:
            result[column] = False if column == "drafted" else None
    result["drafted"] = result["drafted"].fillna(False).astype(bool)
    return result[PLAYER_COLUMNS]

