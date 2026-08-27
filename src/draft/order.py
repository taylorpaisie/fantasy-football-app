"""Reusable snake-draft ordering functions."""

from __future__ import annotations


def _validate(league_size: int, overall_pick: int | None = None) -> None:
    if league_size < 2:
        raise ValueError("league_size must be at least 2")
    if overall_pick is not None and overall_pick < 1:
        raise ValueError("overall_pick must be positive")


def get_round_for_pick(overall_pick: int, league_size: int) -> int:
    """Return the one-based round containing an overall pick."""
    _validate(league_size, overall_pick)
    return (overall_pick - 1) // league_size + 1


def get_team_for_pick(overall_pick: int, league_size: int) -> int:
    """Return the one-based draft slot selecting at an overall snake pick."""
    _validate(league_size, overall_pick)
    round_number = get_round_for_pick(overall_pick, league_size)
    offset = (overall_pick - 1) % league_size
    return offset + 1 if round_number % 2 else league_size - offset


def get_team_draft_slots(team_number: int, league_size: int, rounds: int) -> list[int]:
    """Return all overall selections owned by a draft slot."""
    _validate(league_size)
    if not 1 <= team_number <= league_size:
        raise ValueError("team_number must be between 1 and league_size")
    if rounds < 1:
        raise ValueError("rounds must be positive")
    slots: list[int] = []
    for round_number in range(1, rounds + 1):
        within_round = team_number if round_number % 2 else league_size - team_number + 1
        slots.append((round_number - 1) * league_size + within_round)
    return slots


def get_next_pick_for_team(
    current_pick: int, team_number: int, league_size: int, rounds: int
) -> int | None:
    """Return the team's first pick at or after ``current_pick``."""
    _validate(league_size, current_pick)
    return next(
        (pick for pick in get_team_draft_slots(team_number, league_size, rounds) if pick >= current_pick),
        None,
    )

