"""Defensive adapter around the unofficial ESPN Fantasy Football API.

No ESPN object escapes this module. Consumers receive normalized dataclasses and
DataFrames, which keeps credentials and third-party implementation details out
of the application domain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from src.models import LeagueInfo, LeagueSnapshot, ensure_player_schema


class ESPNConnectionError(RuntimeError):
    """A safe, credential-free ESPN connection error."""


@dataclass(frozen=True, slots=True)
class ESPNCredentials:
    league_id: int | None
    season: int = 2026
    espn_s2: str | None = None
    swid: str | None = None

    @classmethod
    def from_environment(cls) -> "ESPNCredentials":
        raw_id = os.getenv("ESPN_LEAGUE_ID", "").strip()
        raw_season = os.getenv("ESPN_SEASON", "2026").strip()
        return cls(
            league_id=int(raw_id) if raw_id else None,
            season=int(raw_season or 2026),
            espn_s2=os.getenv("ESPN_S2") or None,
            swid=os.getenv("ESPN_SWID") or None,
        )

    @property
    def has_private_auth(self) -> bool:
        return bool(self.espn_s2 and self.swid)

    def validate(self) -> None:
        if self.league_id is None or self.league_id <= 0:
            raise ESPNConnectionError("Enter a valid ESPN league ID.")
        if bool(self.espn_s2) != bool(self.swid):
            raise ESPNConnectionError("Private leagues require both ESPN_S2 and ESPN_SWID.")


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _owner_text(owner: Any) -> str:
    if owner is None:
        return ""
    if isinstance(owner, dict):
        return str(owner.get("displayName") or owner.get("firstName") or owner.get("id") or "")
    if isinstance(owner, (list, tuple)):
        return ", ".join(filter(None, (_owner_text(item) for item in owner)))
    return str(owner)


class ESPNClient:
    """Fetch and normalize one ESPN fantasy league."""

    def __init__(self, credentials: ESPNCredentials, league_factory: Any = None):
        self.credentials = credentials
        self._league_factory = league_factory

    def _factory(self) -> Any:
        if self._league_factory is not None:
            return self._league_factory
        try:
            from espn_api.football import League
        except ImportError as exc:  # pragma: no cover - dependency failure path
            raise ESPNConnectionError("Install dependencies with: pip install -r requirements.txt") from exc
        return League

    def connect(self) -> Any:
        self.credentials.validate()
        try:
            return self._factory()(
                league_id=self.credentials.league_id,
                year=self.credentials.season,
                espn_s2=self.credentials.espn_s2,
                swid=self.credentials.swid,
                debug=False,
            )
        except Exception as exc:
            message = str(exc).lower()
            if any(token in message for token in ("401", "403", "private", "auth", "cookie")):
                detail = "ESPN rejected access. For a private league, refresh both ESPN_S2 and ESPN_SWID."
            elif any(token in message for token in ("404", "not found", "invalid league")):
                detail = "ESPN could not find that league for the selected season."
            else:
                detail = "ESPN is unavailable or returned an unexpected response. Offline mode is still available."
            raise ESPNConnectionError(detail) from exc

    def fetch_snapshot(self) -> LeagueSnapshot:
        league = self.connect()
        return self.normalize_league(league, self.credentials)

    @classmethod
    def normalize_league(cls, league: Any, credentials: ESPNCredentials) -> LeagueSnapshot:
        """Normalize an espn_api League object (also convenient for mocked tests)."""
        settings = _get(league, "settings", default={})
        teams_raw = list(_get(league, "teams", default=[]) or [])
        roster_settings = _get(settings, "roster_settings", default={}) or {}
        lineup_slot_counts = _get(roster_settings, "lineupSlotCounts", "lineup_slot_counts", default={}) or {}
        roster_slots = {str(key): int(value) for key, value in lineup_slot_counts.items() if value}
        team_count = int(_get(settings, "team_count", "teamCount", default=len(teams_raw) or 16))
        scoring_format = str(_get(settings, "scoring_format", "scoringFormat", default="unknown"))
        draft_settings = _get(settings, "draft_settings", default={}) or {}
        draft_rounds = int(_get(draft_settings, "rounds", default=sum(roster_slots.values()) or 15))

        info = LeagueInfo(
            league_id=credentials.league_id,
            name=str(_get(settings, "name", default=_get(league, "league_name", default="ESPN League"))),
            season=credentials.season,
            team_count=team_count,
            scoring_type=scoring_format,
            roster_slots=roster_slots,
            draft_rounds=draft_rounds,
            current_week=_get(league, "current_week", "nfl_week"),
        )
        teams = cls.normalize_teams(teams_raw)
        rosters = cls.normalize_rosters(teams_raw)
        warnings: list[str] = []

        free_agents: list[Any] = []
        try:
            free_agents = list(league.free_agents(size=500) or [])
        except Exception:
            warnings.append("Free-agent data was unavailable; cached or sample players remain usable.")
        players = cls.normalize_players([*cls._roster_players(teams_raw), *free_agents])
        draft_picks = cls.normalize_draft(_get(league, "draft", default=[]) or [])
        matchups = pd.DataFrame()
        try:
            matchups = cls.normalize_matchups(league.scoreboard())
        except Exception:
            warnings.append("Current matchup data was unavailable.")
        return LeagueSnapshot(info, teams, rosters, players, draft_picks, matchups, warnings)

    @staticmethod
    def _roster_players(teams: Iterable[Any]) -> list[Any]:
        return [player for team in teams for player in (_get(team, "roster", default=[]) or [])]

    @staticmethod
    def normalize_teams(teams: Iterable[Any]) -> pd.DataFrame:
        rows = []
        for team in teams:
            rows.append(
                {
                    "team_id": _get(team, "team_id", "teamId", default=None),
                    "team_name": _get(team, "team_name", "teamName", default="Unnamed Team"),
                    "owner": _owner_text(_get(team, "owners", "owner", default="")),
                    "wins": _get(team, "wins", default=None),
                    "losses": _get(team, "losses", default=None),
                    "ties": _get(team, "ties", default=None),
                    "standing": _get(team, "standing", "final_standing", default=None),
                    "points_for": _get(team, "points_for", "pointsFor", default=None),
                    "points_against": _get(team, "points_against", "pointsAgainst", default=None),
                }
            )
        return pd.DataFrame(rows)

    @classmethod
    def normalize_rosters(cls, teams: Iterable[Any]) -> pd.DataFrame:
        rows = []
        for team in teams:
            team_id = _get(team, "team_id", "teamId", default=None)
            for player in _get(team, "roster", default=[]) or []:
                rows.append(
                    {
                        "team_id": team_id,
                        "player_id": str(_get(player, "playerId", "player_id", default="")),
                        "player_name": _get(player, "name", default="Unknown Player"),
                        "position": _get(player, "position", default="UNK"),
                        "nfl_team": _get(player, "proTeam", "pro_team", default="FA"),
                        "lineup_slot": _get(player, "lineupSlot", "slot_position", default="UNKNOWN"),
                        "projected_points": _get(player, "projected_points", "projected_total_points", default=None),
                        "actual_points": _get(player, "total_points", default=None),
                        "injury_status": _get(player, "injuryStatus", "injury_status", default="ACTIVE"),
                        "bye_week": _get(player, "bye_week", default=None),
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def normalize_players(players: Iterable[Any]) -> pd.DataFrame:
        rows: dict[str, dict[str, Any]] = {}
        for index, player in enumerate(players):
            espn_id = _get(player, "playerId", "player_id", default=None)
            player_id = f"espn_{espn_id}" if espn_id is not None else f"espn_unknown_{index}"
            rows[player_id] = {
                "player_id": player_id,
                "espn_player_id": espn_id,
                "player_name": _get(player, "name", default="Unknown Player"),
                "position": _get(player, "position", default="UNK"),
                "team": _get(player, "proTeam", "pro_team", default="FA"),
                "bye_week": _get(player, "bye_week", default=None),
                "injury_status": _get(player, "injuryStatus", "injury_status", default="ACTIVE"),
                "espn_rank": _get(player, "rank", "posRank", default=None),
                "ownership_pct": _get(player, "percent_owned", "percentOwned", default=None),
                "projected_points": _get(player, "projected_total_points", "projected_points", default=None),
                "actual_points": _get(player, "total_points", default=None),
                "adp": _get(player, "average_draft_position", "adp", default=None),
                "consensus_rank": None,
                "model_rank": None,
                "position_rank": _get(player, "posRank", default=None),
                "tier": None,
                "drafted": bool(_get(player, "acquisitionType", default="") == "DRAFT"),
            }
        return ensure_player_schema(pd.DataFrame(rows.values())) if rows else ensure_player_schema(pd.DataFrame())

    @staticmethod
    def normalize_draft(picks: Iterable[Any]) -> pd.DataFrame:
        rows = []
        for pick in picks:
            player = _get(pick, "player", default=None)
            team = _get(pick, "team", default=None)
            rows.append(
                {
                    "overall_pick": _get(pick, "overall_pick", "overallPickNumber", default=None),
                    "round_number": _get(pick, "round_num", "roundId", default=None),
                    "round_pick": _get(pick, "round_pick", "roundPickNumber", default=None),
                    "team_id": _get(team, "team_id", "teamId", default=_get(pick, "team_id", default=None)),
                    "player_id": str(_get(pick, "playerId", default=_get(player, "playerId", default=""))),
                    "player_name": _get(pick, "playerName", default=_get(player, "name", default="Unknown Player")),
                    "keeper": bool(_get(pick, "keeper_status", "keeper", default=False)),
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def normalize_matchups(matchups: Iterable[Any]) -> pd.DataFrame:
        rows = []
        for matchup in matchups or []:
            home = _get(matchup, "home_team", default=None)
            away = _get(matchup, "away_team", default=None)
            rows.append(
                {
                    "home_team_id": _get(home, "team_id", default=None),
                    "home_team": _get(home, "team_name", default="TBD"),
                    "home_score": _get(matchup, "home_score", default=None),
                    "away_team_id": _get(away, "team_id", default=None),
                    "away_team": _get(away, "team_name", default="TBD"),
                    "away_score": _get(matchup, "away_score", default=None),
                }
            )
        return pd.DataFrame(rows)

