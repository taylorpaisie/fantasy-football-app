"""Conservative player identity matching across data providers."""

from __future__ import annotations

import logging
import re
import unicodedata

import pandas as pd

LOGGER = logging.getLogger(__name__)
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_player_name(name: str) -> str:
    """Normalize accents, punctuation, whitespace, and common suffixes."""
    ascii_name = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    tokens = re.sub(r"[^a-z0-9 ]", " ", ascii_name.lower()).split()
    if tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_team(team: str | None) -> str:
    aliases = {"JAC": "JAX", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LAR"}
    value = str(team or "").upper().strip()
    return aliases.get(value, value)


def match_players(
    left: pd.DataFrame, right: pd.DataFrame
) -> tuple[list[dict[str, int]], pd.DataFrame, pd.DataFrame]:
    """Return exact, unambiguous matches plus unmatched rows from both sources."""
    left_work = left.reset_index(drop=True).copy()
    right_work = right.reset_index(drop=True).copy()
    for frame in (left_work, right_work):
        frame["_name"] = frame["player_name"].map(normalize_player_name)
        frame["_position"] = frame["position"].fillna("").astype(str).str.upper()
        frame["_team"] = frame.get("team", pd.Series("", index=frame.index)).map(normalize_team)
    matches: list[dict[str, int]] = []
    used_right: set[int] = set()
    for left_idx, row in left_work.iterrows():
        candidates = right_work[
            (right_work["_name"] == row["_name"]) & (right_work["_position"] == row["_position"])
        ]
        if len(candidates) > 1 and row["_team"]:
            candidates = candidates[candidates["_team"] == row["_team"]]
        candidates = candidates[~candidates.index.isin(used_right)]
        if len(candidates) == 1:
            right_idx = int(candidates.index[0])
            used_right.add(right_idx)
            matches.append({"left_index": int(left_idx), "right_index": right_idx})
        elif len(candidates) > 1:
            LOGGER.warning("Ambiguous player match: %s (%s)", row["player_name"], row["position"])
    used_left = {item["left_index"] for item in matches}
    left_unmatched = left.loc[~left.reset_index(drop=True).index.isin(used_left)].copy()
    right_unmatched = right.loc[~right.reset_index(drop=True).index.isin(used_right)].copy()
    if not left_unmatched.empty or not right_unmatched.empty:
        LOGGER.info("Player matching left %d and right %d unmatched rows", len(left_unmatched), len(right_unmatched))
    return matches, left_unmatched, right_unmatched

