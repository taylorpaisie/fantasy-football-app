"""Load normalized player data from CSV or a deterministic offline sample."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.models import PLAYER_COLUMNS, ensure_player_schema


POSITION_COUNTS = {"QB": 38, "RB": 76, "WR": 88, "TE": 38, "D/ST": 20, "K": 20}
POSITION_BASE = {"QB": 315, "RB": 255, "WR": 245, "TE": 205, "D/ST": 135, "K": 130}
NFL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA", "MIN", "NE",
    "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]


def generate_sample_players(seed: int = 2026) -> pd.DataFrame:
    """Create clearly synthetic, internally consistent players for offline use."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    global_rank = 1
    position_order = ["RB", "WR", "QB", "TE", "D/ST", "K"]
    candidates = []
    for position in position_order:
        for index in range(1, POSITION_COUNTS[position] + 1):
            decay = {"QB": 3.0, "RB": 2.15, "WR": 1.85, "TE": 2.2, "D/ST": 1.0, "K": 0.8}[position]
            points = POSITION_BASE[position] - decay * index + rng.normal(0, 3)
            value = points + {"RB": 38, "WR": 34, "TE": 12, "QB": 4, "D/ST": -75, "K": -85}[position]
            candidates.append((value, position, index, max(points, 45.0)))
    candidates.sort(reverse=True)
    for _, position, index, points in candidates:
        adp = max(1.0, global_rank + rng.normal(0, 9))
        espn_rank = max(1, int(round(global_rank + rng.normal(0, 13))))
        rows.append(
            {
                "player_id": f"sample_{position.replace('/', '')}_{index:03d}",
                "espn_player_id": None,
                "player_name": f"Sample {position} Player {index:02d}",
                "position": position,
                "team": NFL_TEAMS[(index - 1) % len(NFL_TEAMS)],
                "bye_week": 5 + (index % 10),
                "injury_status": "ACTIVE",
                "espn_rank": espn_rank,
                "ownership_pct": None,
                "projected_points": round(points, 1),
                "actual_points": None,
                "adp": round(adp, 1),
                "consensus_rank": global_rank,
                "model_rank": global_rank,
                "position_rank": index,
                "tier": max(1, (index - 1) // {"QB": 6, "RB": 10, "WR": 12, "TE": 6, "D/ST": 5, "K": 5}[position] + 1),
                "drafted": False,
            }
        )
        global_rank += 1
    return ensure_player_schema(pd.DataFrame(rows).sort_values("model_rank"))


def load_players(csv_path: str | Path | None = None) -> pd.DataFrame:
    """Load a normalized CSV, falling back to the labeled sample dataset."""
    if csv_path:
        path = Path(csv_path)
        if path.exists():
            frame = pd.read_csv(path)
            required = {"player_name", "position"}
            missing = required - set(frame.columns)
            if missing:
                raise ValueError(f"Player CSV missing required columns: {sorted(missing)}")
            if "player_id" not in frame:
                frame["player_id"] = [f"external_{i}" for i in range(len(frame))]
            return ensure_player_schema(frame)
    return generate_sample_players()


def merge_player_sources(base: pd.DataFrame, updates: pd.DataFrame) -> pd.DataFrame:
    """Overlay confidently matched ESPN fields onto the model player pool."""
    if updates.empty:
        return ensure_player_schema(base)
    from src.data.player_matching import match_players

    matches, _, _ = match_players(base, updates)
    result = base.copy()
    update_index = updates.reset_index(drop=True)
    for match in matches:
        left_idx, right_idx = match["left_index"], match["right_index"]
        for column in ("espn_player_id", "espn_rank", "ownership_pct", "injury_status", "bye_week"):
            value = update_index.loc[right_idx, column] if column in update_index else None
            if pd.notna(value):
                result.loc[left_idx, column] = value
    return ensure_player_schema(result)

