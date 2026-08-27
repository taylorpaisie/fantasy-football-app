"""Transparent, configurable draft recommendation scoring."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.roster.roster import roster_needs, roster_summary


def _percentile(series: pd.Series, ascending: bool = True) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    fill = numeric.median() if numeric.notna().any() else 0.0
    return numeric.fillna(fill).rank(pct=True, ascending=ascending)


def recommend_players(
    available: pd.DataFrame,
    probabilities: pd.DataFrame,
    scarcity: pd.DataFrame,
    my_roster: Sequence[Any],
    roster_requirements: Mapping[str, int],
    weights: Mapping[str, float],
    current_round: int,
    strategy: Mapping[str, int] | None = None,
) -> pd.DataFrame:
    """Rank remaining players and attach human-readable, probabilistic reasons."""
    if available.empty:
        return available.copy()
    frame = available.merge(probabilities, on="player_id", how="left")
    frame["prob_available_next_pick"] = frame["prob_available_next_pick"].fillna(1.0)
    frame["prob_drafted_before_next_pick"] = 1.0 - frame["prob_available_next_pick"]
    scarcity_map = scarcity.set_index("position")["scarcity_score"].to_dict()
    status_map = scarcity.set_index("position")["status"].to_dict()
    drop_map = scarcity.set_index("position")["tier_drop"].to_dict()
    needs = roster_needs(my_roster, roster_requirements)
    counts = roster_summary(my_roster)
    strategy = strategy or {}

    frame["component_player_value"] = 1.0 - _percentile(frame["model_rank"], ascending=True)
    frame["component_projected_points"] = _percentile(frame["projected_points"], ascending=True)
    model_rank = pd.to_numeric(frame["model_rank"], errors="coerce")
    adp = pd.to_numeric(frame["adp"], errors="coerce")
    value_gap = (adp - model_rank).fillna(0)
    frame["component_adp_value"] = (value_gap.rank(pct=True) - 0.5).clip(-0.5, 0.5) + 0.5
    frame["component_tier_value"] = 1.0 - _percentile(frame["tier"], ascending=True)
    frame["component_scarcity"] = frame["position"].map(scarcity_map).fillna(0) / 100
    frame["component_roster_need"] = frame["position"].map(needs).fillna(0)
    frame["component_availability_risk"] = frame["prob_drafted_before_next_pick"]
    replacement = frame.groupby("position")["projected_points"].transform(
        lambda values: values - values.quantile(0.35)
    )
    frame["component_replacement_value"] = _percentile(replacement, ascending=True)

    total_weight = max(sum(float(value) for value in weights.values()), 1e-9)
    raw = sum(
        frame[f"component_{name}"] * float(weight)
        for name, weight in weights.items()
        if f"component_{name}" in frame
    ) / total_weight
    penalty = pd.Series(0.0, index=frame.index)
    early_cutoff = int(strategy.get("early_round_cutoff", 8))
    qb_cutoff = int(strategy.get("second_qb_penalty_before_round", 10))
    late_round = int(strategy.get("defense_kicker_round", 13))
    if current_round < late_round:
        penalty += frame["position"].isin(["D/ST", "K"]).astype(float) * 0.48
    if current_round < qb_cutoff and counts.get("QB", 0) >= 1:
        penalty += (frame["position"] == "QB").astype(float) * 0.28
    if current_round <= early_cutoff:
        max_same = int(strategy.get("max_early_same_position", 4))
        for position, count in counts.items():
            if count >= max_same:
                penalty += (frame["position"] == position).astype(float) * 0.32
        if counts.get("RB", 0) == 0 and counts.get("WR", 0) >= 4:
            penalty += (frame["position"] == "WR").astype(float) * 0.35
    frame["recommendation_score"] = ((raw - penalty).clip(0, 1) * 100).round(1)
    frame = frame.sort_values(["recommendation_score", "model_rank"], ascending=[False, True]).reset_index(drop=True)
    frame["recommendation_rank"] = np.arange(1, len(frame) + 1)

    def reasons(row: pd.Series) -> list[str]:
        messages = []
        if row["component_player_value"] >= 0.8:
            messages.append("Elite remaining model value")
        if row["component_projected_points"] >= 0.8:
            messages.append(f"One of the strongest remaining {row['position']} projections")
        status = status_map.get(row["position"], "LOW")
        if status in ("HIGH", "VERY HIGH"):
            messages.append(f"{row['position']} scarcity is {status}")
        survival = row["prob_available_next_pick"]
        if survival < 0.35:
            messages.append(f"Only {survival:.0%} estimated chance to reach your next pick")
        elif survival > 0.75:
            messages.append(f"May remain available ({survival:.0%} estimated chance)")
        drop = drop_map.get(row["position"], 0)
        if drop >= 8:
            messages.append(f"Projected {row['position']} tier drop is about {drop:.1f} points")
        if needs.get(row["position"], 0) >= 0.75:
            messages.append("Fills a currently open starting need")
        return messages[:4] or ["Balanced value across rank, projection, and draft cost"]

    frame["reasons"] = frame.apply(reasons, axis=1)
    return frame


def espn_value_gaps(players: pd.DataFrame) -> pd.DataFrame:
    """Positive gap means the model likes a player more than ESPN's room rank."""
    frame = players.copy()
    frame["difference"] = pd.to_numeric(frame["espn_rank"], errors="coerce") - pd.to_numeric(
        frame["model_rank"], errors="coerce"
    )
    frame = frame.dropna(subset=["difference"])
    frame["interpretation"] = np.select(
        [frame["difference"] >= 10, frame["difference"] <= -10],
        ["ESPN room may undervalue player", "ESPN room may push player earlier"],
        default="Ranks are broadly aligned",
    )
    return frame[["player_name", "position", "espn_rank", "model_rank", "difference", "interpretation"]].sort_values(
        "difference", ascending=False
    )

