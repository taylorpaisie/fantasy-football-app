"""Monte Carlo next-pick availability simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.draft.order import get_round_for_pick, get_team_for_pick


@dataclass(slots=True)
class SimulationResult:
    probabilities: pd.DataFrame
    expected_by_position: dict[str, float]
    picks_simulated: int


def _numeric(frame: pd.DataFrame, column: str, fallback: np.ndarray) -> np.ndarray:
    if column not in frame:
        return fallback.astype(float)
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
    return np.where(np.isnan(values), fallback, values)


def _need_multiplier(position: str, counts: Mapping[str, int], round_number: int) -> float:
    target = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "D/ST": 0, "K": 0}
    current = counts.get(position, 0)
    if position in ("D/ST", "K"):
        return 0.06 if round_number < 11 else 1.2
    if current < target.get(position, 0):
        return 1.45
    if position == "QB" and current >= 1 and round_number < 10:
        return 0.18
    return 0.8 if current >= target.get(position, 1) + 2 else 1.0


def simulate_availability(
    players: pd.DataFrame,
    first_simulated_pick: int,
    target_pick: int,
    league_size: int,
    simulations: int = 5000,
    history: Sequence[Any] | None = None,
    weights: Mapping[str, float] | None = None,
    seed: int = 2026,
) -> SimulationResult:
    """Estimate whether each player survives picks before ``target_pick``.

    Opponents react to ADP, consensus/model rank, ESPN rank, projections, roster
    construction, and stochastic reaches. The simulator intentionally does not
    model opponents as optimizers.
    """
    available = players.loc[~players["drafted"].fillna(False)].reset_index(drop=True).copy()
    pick_numbers = list(range(first_simulated_pick, target_pick))
    if simulations < 1:
        raise ValueError("simulations must be positive")
    if target_pick <= first_simulated_pick or available.empty:
        probs = available[["player_id"]].copy()
        probs["prob_available_next_pick"] = 1.0
        probs["prob_drafted_before_next_pick"] = 0.0
        return SimulationResult(probs, {}, 0)

    default_weights = {
        "adp": 0.38,
        "consensus_rank": 0.20,
        "espn_rank": 0.25,
        "projected_points": 0.07,
        "roster_need": 0.10,
        "reach_probability": 0.08,
        "randomness": 0.22,
    }
    model = {**default_weights, **(weights or {})}
    n_players = len(available)
    fallback_rank = np.arange(1, n_players + 1, dtype=float)
    adp = _numeric(available, "adp", fallback_rank)
    consensus = _numeric(available, "consensus_rank", adp)
    espn_rank = _numeric(available, "espn_rank", adp)
    projection = _numeric(available, "projected_points", np.zeros(n_players))
    projection = (projection - projection.min()) / max(float(np.ptp(projection)), 1.0)
    positions = available["position"].astype(str).to_numpy()
    rng = np.random.default_rng(seed)
    drafted_counts = np.zeros(n_players, dtype=np.int32)
    positional_totals: dict[str, int] = {position: 0 for position in set(positions)}

    initial_rosters: dict[int, dict[str, int]] = {team: {} for team in range(1, league_size + 1)}
    for prior in history or []:
        team = int(getattr(prior, "team_number", prior.get("team_number", 0) if isinstance(prior, dict) else 0))
        position = str(getattr(prior, "position", prior.get("position", "") if isinstance(prior, dict) else ""))
        if team in initial_rosters and position:
            initial_rosters[team][position] = initial_rosters[team].get(position, 0) + 1

    for _ in range(simulations):
        taken = np.zeros(n_players, dtype=bool)
        rosters = {team: counts.copy() for team, counts in initial_rosters.items()}
        for overall_pick in pick_numbers:
            candidates = np.flatnonzero(~taken)
            if not len(candidates):
                break
            team = get_team_for_pick(overall_pick, league_size)
            round_number = get_round_for_pick(overall_pick, league_size)
            rank_scale = max(10.0, league_size * 0.9)
            adp_pressure = np.exp(-np.abs(adp[candidates] - overall_pick) / rank_scale)
            consensus_pressure = np.exp(-np.abs(consensus[candidates] - overall_pick) / (rank_scale * 1.3))
            espn_pressure = np.exp(-np.abs(espn_rank[candidates] - overall_pick) / (rank_scale * 1.15))
            need = np.array([
                _need_multiplier(positions[idx], rosters[team], round_number) for idx in candidates
            ])
            score = (
                model["adp"] * adp_pressure
                + model["consensus_rank"] * consensus_pressure
                + model["espn_rank"] * espn_pressure
                + model["projected_points"] * projection[candidates]
                + model["roster_need"] * need
            )
            score *= rng.lognormal(mean=0.0, sigma=model["randomness"], size=len(candidates))
            if rng.random() < model["reach_probability"]:
                plausible = candidates[np.argsort(adp[candidates])[: min(70, len(candidates))]]
                chosen = int(rng.choice(plausible))
            else:
                probabilities = np.maximum(score, 1e-9)
                probabilities /= probabilities.sum()
                chosen = int(rng.choice(candidates, p=probabilities))
            taken[chosen] = True
            position = positions[chosen]
            rosters[team][position] = rosters[team].get(position, 0) + 1
            positional_totals[position] = positional_totals.get(position, 0) + 1
        drafted_counts += taken

    probability_drafted = drafted_counts / simulations
    probabilities = pd.DataFrame(
        {
            "player_id": available["player_id"],
            "prob_available_next_pick": 1.0 - probability_drafted,
            "prob_drafted_before_next_pick": probability_drafted,
        }
    )
    expected = {position: total / simulations for position, total in positional_totals.items()}
    return SimulationResult(probabilities, expected, len(pick_numbers))

