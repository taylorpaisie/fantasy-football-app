"""Fantasy scoring helpers and scoring-format detection."""

from __future__ import annotations

from typing import Mapping


STANDARD_RULES = {
    "passingYards": 0.04,
    "passingTouchdowns": 4.0,
    "passingInterceptions": -2.0,
    "rushingYards": 0.1,
    "rushingTouchdowns": 6.0,
    "receivingYards": 0.1,
    "receivingTouchdowns": 6.0,
    "receptions": 0.0,
    "fumblesLost": -2.0,
}


def score_projection(stats: Mapping[str, float], rules: Mapping[str, float] | None = None) -> float:
    active_rules = {**STANDARD_RULES, **(rules or {})}
    return round(sum(float(stats.get(stat, 0) or 0) * multiplier for stat, multiplier in active_rules.items()), 2)


def infer_scoring_label(reception_points: float | None) -> str:
    if reception_points is None:
        return "unknown"
    if reception_points >= 0.9:
        return "PPR"
    if reception_points >= 0.4:
        return "half-PPR"
    return "standard"

