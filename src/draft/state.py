"""Serializable manual draft state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .order import get_round_for_pick, get_team_for_pick


@dataclass(slots=True)
class DraftPick:
    overall_pick: int
    round_number: int
    team_number: int
    player_id: str
    player_name: str
    position: str
    nfl_team: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DraftState:
    league_size: int = 16
    rounds: int = 15
    my_draft_position: int = 10
    current_pick: int = 1
    history: list[DraftPick] = field(default_factory=list)
    selected_espn_team_id: int | None = None

    @property
    def total_picks(self) -> int:
        return self.league_size * self.rounds

    @property
    def is_complete(self) -> bool:
        return self.current_pick > self.total_picks

    @property
    def drafted_player_ids(self) -> set[str]:
        return {pick.player_id for pick in self.history}

    @property
    def my_roster(self) -> list[DraftPick]:
        return [pick for pick in self.history if pick.team_number == self.my_draft_position]

    def draft_player(self, player: Mapping[str, Any]) -> DraftPick:
        """Record the player at the current pick and advance the draft."""
        if self.is_complete:
            raise ValueError("The draft is already complete")
        player_id = str(player["player_id"])
        if player_id in self.drafted_player_ids:
            raise ValueError(f"{player.get('player_name', player_id)} is already drafted")
        pick = DraftPick(
            overall_pick=self.current_pick,
            round_number=get_round_for_pick(self.current_pick, self.league_size),
            team_number=get_team_for_pick(self.current_pick, self.league_size),
            player_id=player_id,
            player_name=str(player["player_name"]),
            position=str(player["position"]),
            nfl_team=str(player.get("team") or ""),
        )
        self.history.append(pick)
        self.current_pick += 1
        return pick

    def undo_last_pick(self) -> DraftPick | None:
        """Remove and return the most recent selection."""
        if not self.history:
            return None
        pick = self.history.pop()
        self.current_pick = pick.overall_pick
        return pick

    def correct_pick(self, overall_pick: int, player: Mapping[str, Any]) -> DraftPick:
        """Replace a prior selection while preserving its team and pick number."""
        index = next((i for i, item in enumerate(self.history) if item.overall_pick == overall_pick), None)
        if index is None:
            raise ValueError(f"Pick {overall_pick} is not in draft history")
        player_id = str(player["player_id"])
        if any(p.player_id == player_id and p.overall_pick != overall_pick for p in self.history):
            raise ValueError("Replacement player is already drafted")
        old = self.history[index]
        replacement = DraftPick(
            overall_pick=old.overall_pick,
            round_number=old.round_number,
            team_number=old.team_number,
            player_id=player_id,
            player_name=str(player["player_name"]),
            position=str(player["position"]),
            nfl_team=str(player.get("team") or ""),
        )
        self.history[index] = replacement
        return replacement

    def reset(self) -> None:
        self.current_pick = 1
        self.history.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "league_size": self.league_size,
            "rounds": self.rounds,
            "my_draft_position": self.my_draft_position,
            "current_pick": self.current_pick,
            "selected_espn_team_id": self.selected_espn_team_id,
            "history": [asdict(pick) for pick in self.history],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DraftState":
        allowed = {"league_size", "rounds", "my_draft_position", "current_pick", "selected_espn_team_id"}
        state = cls(**{key: payload[key] for key in allowed if key in payload})
        state.history = [DraftPick(**pick) for pick in payload.get("history", [])]
        return state

