"""Position-level pressure and tier-drop analysis."""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd


def calculate_positional_scarcity(
    available: pd.DataFrame,
    expected_drafted: Mapping[str, float],
    league_size: int,
) -> pd.DataFrame:
    rows = []
    for position in ("RB", "WR", "QB", "TE", "D/ST", "K"):
        group = available[available["position"] == position].copy()
        if group.empty:
            rows.append({"position": position, "quality_remaining": 0, "expected_drafted": 0.0,
                         "tier_drop": 0.0, "scarcity_score": 100.0, "status": "VERY HIGH"})
            continue
        projected = pd.to_numeric(group["projected_points"], errors="coerce").fillna(0)
        quality_cutoff = projected.nlargest(min(league_size, len(projected))).min()
        quality_remaining = int((projected >= quality_cutoff).sum())
        best_tier = pd.to_numeric(group["tier"], errors="coerce").min()
        current = group[pd.to_numeric(group["tier"], errors="coerce") == best_tier]
        later = group[pd.to_numeric(group["tier"], errors="coerce") > best_tier]
        tier_drop = max(
            float(pd.to_numeric(current["projected_points"], errors="coerce").mean() -
                  pd.to_numeric(later["projected_points"], errors="coerce").max())
            if not later.empty else 0.0,
            0.0,
        )
        expected = float(expected_drafted.get(position, 0.0))
        pressure = min(expected / max(quality_remaining, 1), 1.0)
        depth_pressure = max(0.0, 1.0 - quality_remaining / max(league_size * 1.5, 1))
        drop_pressure = min(tier_drop / 25.0, 1.0)
        score = 100 * (0.48 * pressure + 0.30 * depth_pressure + 0.22 * drop_pressure)
        status = "LOW" if score < 25 else "MODERATE" if score < 50 else "HIGH" if score < 75 else "VERY HIGH"
        rows.append(
            {
                "position": position,
                "quality_remaining": quality_remaining,
                "expected_drafted": round(expected, 1),
                "tier_drop": round(tier_drop, 1),
                "scarcity_score": round(score, 1),
                "status": status,
            }
        )
    return pd.DataFrame(rows)

