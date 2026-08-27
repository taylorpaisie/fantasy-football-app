"""Roster composition and need calculations."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

FLEX_POSITIONS = {"RB", "WR", "TE"}


def _position(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("position", ""))
    return str(getattr(item, "position", ""))


def roster_summary(players: Iterable[Any]) -> dict[str, int]:
    return dict(Counter(_position(player) for player in players if _position(player)))


def roster_needs(players: Iterable[Any], requirements: Mapping[str, int]) -> dict[str, float]:
    """Return need intensity from 0 (filled) to 1 (empty), with FLEX awareness."""
    counts = roster_summary(players)
    needs: dict[str, float] = {}
    for position in ("QB", "RB", "WR", "TE", "D/ST", "K"):
        required = int(requirements.get(position, 0))
        missing = max(required - counts.get(position, 0), 0)
        needs[position] = missing / max(required, 1) if required else 0.0
    flex_required = int(requirements.get("FLEX", 0))
    flex_surplus = sum(max(counts.get(position, 0) - int(requirements.get(position, 0)), 0) for position in FLEX_POSITIONS)
    if flex_required > flex_surplus:
        for position in FLEX_POSITIONS:
            needs[position] = min(1.0, needs[position] + 0.25)
    return needs

