"""SQLite persistence without ESPN credentials."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from src.draft.state import DraftState


SCHEMA = """
CREATE TABLE IF NOT EXISTS league (
    league_id INTEGER, season INTEGER, name TEXT, platform TEXT,
    settings_json TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (league_id, season)
);
CREATE TABLE IF NOT EXISTS teams (
    league_id INTEGER, season INTEGER, team_id INTEGER, team_name TEXT,
    owner TEXT, data_json TEXT, PRIMARY KEY (league_id, season, team_id)
);
CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY, espn_player_id INTEGER, player_name TEXT,
    position TEXT, nfl_team TEXT, data_json TEXT
);
CREATE TABLE IF NOT EXISTS draft_picks (
    context TEXT, overall_pick INTEGER, round_number INTEGER, team_number INTEGER,
    player_id TEXT, player_name TEXT, position TEXT, nfl_team TEXT, timestamp TEXT,
    PRIMARY KEY (context, overall_pick)
);
CREATE TABLE IF NOT EXISTS rosters (
    league_id INTEGER, season INTEGER, team_id INTEGER, player_id TEXT,
    lineup_slot TEXT, data_json TEXT,
    PRIMARY KEY (league_id, season, team_id, player_id)
);
CREATE TABLE IF NOT EXISTS projections (
    player_id TEXT, season INTEGER, source TEXT, projected_points REAL,
    data_json TEXT, PRIMARY KEY (player_id, season, source)
);
CREATE TABLE IF NOT EXISTS rankings (
    player_id TEXT, season INTEGER, source TEXT, rank REAL,
    data_json TEXT, PRIMARY KEY (player_id, season, source)
);
CREATE TABLE IF NOT EXISTS simulation_results (
    context TEXT, state_hash TEXT, result_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (context, state_hash)
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, league_id INTEGER, season INTEGER,
    transaction_type TEXT, data_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    """Small repository for local, non-secret application state."""

    def __init__(self, path: str | Path = "data/fantasy_war_room.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def set_setting(self, key: str, value: Any) -> None:
        if any(secret in key.lower() for secret in ("espn_s2", "swid", "cookie", "password", "secret")):
            raise ValueError("Credentials must never be written to SQLite")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO app_settings(key, value_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=CURRENT_TIMESTAMP",
                (key, json.dumps(value)),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as connection:
            row = connection.execute("SELECT value_json FROM app_settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def save_draft_state(self, state: DraftState, context: str = "default") -> None:
        """Persist manual picks and non-secret state atomically."""
        metadata = state.to_dict()
        metadata.pop("history", None)
        with self.connect() as connection:
            connection.execute("DELETE FROM draft_picks WHERE context = ?", (context,))
            connection.executemany(
                """INSERT INTO draft_picks(
                    context, overall_pick, round_number, team_number, player_id,
                    player_name, position, nfl_team, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (context, p.overall_pick, p.round_number, p.team_number, p.player_id,
                     p.player_name, p.position, p.nfl_team, p.timestamp)
                    for p in state.history
                ],
            )
            connection.execute(
                "INSERT INTO app_settings(key, value_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=CURRENT_TIMESTAMP",
                (f"draft_state:{context}", json.dumps(metadata)),
            )

    def load_draft_state(self, context: str = "default") -> DraftState | None:
        metadata = self.get_setting(f"draft_state:{context}")
        if metadata is None:
            return None
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM draft_picks WHERE context = ? ORDER BY overall_pick", (context,)
            ).fetchall()
        metadata["history"] = [
            {
                "overall_pick": row["overall_pick"],
                "round_number": row["round_number"],
                "team_number": row["team_number"],
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "position": row["position"],
                "nfl_team": row["nfl_team"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
        return DraftState.from_dict(metadata)

    def save_league_snapshot(self, league: Mapping[str, Any], teams: list[Mapping[str, Any]]) -> None:
        league_id = league.get("league_id")
        season = league.get("season")
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO league(league_id, season, name, platform, settings_json) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(league_id, season) DO UPDATE SET name=excluded.name, platform=excluded.platform, "
                "settings_json=excluded.settings_json, updated_at=CURRENT_TIMESTAMP",
                (league_id, season, league.get("name"), league.get("platform"), json.dumps(dict(league))),
            )
            for team in teams:
                connection.execute(
                    "INSERT INTO teams(league_id, season, team_id, team_name, owner, data_json) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(league_id, season, team_id) DO UPDATE SET "
                    "team_name=excluded.team_name, owner=excluded.owner, data_json=excluded.data_json",
                    (league_id, season, team.get("team_id"), team.get("team_name"), team.get("owner"), json.dumps(dict(team))),
                )

