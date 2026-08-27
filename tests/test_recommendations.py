from types import SimpleNamespace

import pandas as pd

from src.data.loaders import generate_sample_players
from src.recommendations.engine import espn_value_gaps, recommend_players
from src.recommendations.scarcity import calculate_positional_scarcity


WEIGHTS = {
    "player_value": 0.24,
    "projected_points": 0.18,
    "adp_value": 0.08,
    "tier_value": 0.10,
    "scarcity": 0.14,
    "roster_need": 0.12,
    "availability_risk": 0.10,
    "replacement_value": 0.04,
}


def test_recommendation_ordering_and_reasons():
    players = generate_sample_players().head(60)
    probabilities = pd.DataFrame({
        "player_id": players["player_id"],
        "prob_available_next_pick": 0.5,
        "prob_drafted_before_next_pick": 0.5,
    })
    scarcity = calculate_positional_scarcity(players, {"RB": 5, "WR": 4, "QB": 1, "TE": 1}, 16)
    ranked = recommend_players(
        players, probabilities, scarcity, [],
        {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "D/ST": 1, "K": 1},
        WEIGHTS, current_round=1,
    )
    assert ranked["recommendation_score"].is_monotonic_decreasing
    assert ranked.iloc[0]["recommendation_rank"] == 1
    assert ranked.iloc[0]["reasons"]
    assert not ranked.head(10)["position"].isin(["D/ST", "K"]).any()


def test_second_qb_receives_early_penalty():
    players = generate_sample_players()
    qb = players[players["position"] == "QB"].head(1)
    probabilities = pd.DataFrame({"player_id": players["player_id"], "prob_available_next_pick": 0.5})
    scarcity = calculate_positional_scarcity(players, {}, 16)
    roster = [SimpleNamespace(position="QB")]
    ranked = recommend_players(
        players, probabilities, scarcity, roster,
        {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "D/ST": 1, "K": 1},
        WEIGHTS, current_round=3, strategy={"second_qb_penalty_before_round": 10, "defense_kicker_round": 13},
    )
    qb_score = ranked.loc[ranked["player_id"] == qb.iloc[0]["player_id"], "recommendation_score"].iloc[0]
    no_qb_ranked = recommend_players(
        players, probabilities, scarcity, [],
        {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "D/ST": 1, "K": 1},
        WEIGHTS, current_round=3, strategy={"second_qb_penalty_before_round": 10, "defense_kicker_round": 13},
    )
    no_qb_score = no_qb_ranked.loc[no_qb_ranked["player_id"] == qb.iloc[0]["player_id"], "recommendation_score"].iloc[0]
    assert qb_score < no_qb_score


def test_espn_value_gap_sign_convention():
    players = pd.DataFrame([
        {"player_name": "Value", "position": "RB", "espn_rank": 30, "model_rank": 10},
        {"player_name": "Reach", "position": "WR", "espn_rank": 5, "model_rank": 25},
    ])
    gaps = espn_value_gaps(players)
    assert gaps.iloc[0]["difference"] == 20
    assert "undervalue" in gaps.iloc[0]["interpretation"]

