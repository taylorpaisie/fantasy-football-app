"""Reconcile normalized ESPN draft results with manual draft state."""

from __future__ import annotations

import pandas as pd

from src.draft.state import DraftState


def apply_normalized_draft_picks(
    state: DraftState,
    picks: pd.DataFrame,
    players: pd.DataFrame,
    *,
    replace_existing: bool = False,
) -> tuple[int, list[str]]:
    """Import contiguous normalized picks without coupling state to ESPN objects."""
    warnings: list[str] = []
    if state.history and not replace_existing:
        return 0, ["Manual draft history exists; it was preserved. Reset it before importing ESPN results."]
    if picks.empty:
        return 0, ["ESPN did not return draft selections."]
    if replace_existing:
        state.reset()
    ordered = picks.dropna(subset=["overall_pick"]).sort_values("overall_pick")
    imported = 0
    for _, pick in ordered.iterrows():
        overall = int(pick["overall_pick"])
        if overall < state.current_pick:
            continue
        if overall != state.current_pick:
            warnings.append(f"Stopped at missing ESPN pick #{state.current_pick}; later picks were not guessed.")
            break
        raw_id = str(pick.get("player_id") or "")
        matches = players[players["espn_player_id"].astype(str) == raw_id] if "espn_player_id" in players else pd.DataFrame()
        if matches.empty and pick.get("player_name"):
            matches = players[players["player_name"].str.casefold() == str(pick["player_name"]).casefold()]
        if len(matches) == 1:
            player = matches.iloc[0].to_dict()
        else:
            player = {
                "player_id": f"espn_{raw_id}" if raw_id else f"espn_pick_{overall}",
                "player_name": str(pick.get("player_name") or f"ESPN Player #{raw_id}"),
                "position": str(pick.get("position") or "UNK"),
                "team": "",
            }
            if len(matches) > 1:
                warnings.append(f"Pick #{overall} had an ambiguous player match; ESPN pick identity was retained.")
        state.draft_player(player)
        imported += 1
    return imported, warnings

