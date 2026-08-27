import pandas as pd

from src.data.player_matching import match_players, normalize_player_name, normalize_team


def test_name_and_team_normalization():
    assert normalize_player_name("D'Andre Swift Jr.") == "d andre swift"
    assert normalize_player_name("José Núñez III") == "jose nunez"
    assert normalize_team("JAC") == "JAX"


def test_unambiguous_match_uses_name_position_and_team():
    left = pd.DataFrame([{"player_name": "D'Andre Swift Jr.", "position": "RB", "team": "CHI"}])
    right = pd.DataFrame([{"player_name": "D Andre Swift", "position": "RB", "team": "CHI"}])
    matches, left_unmatched, right_unmatched = match_players(left, right)
    assert matches == [{"left_index": 0, "right_index": 0}]
    assert left_unmatched.empty
    assert right_unmatched.empty


def test_ambiguous_matches_are_not_silently_merged():
    left = pd.DataFrame([{"player_name": "John Smith", "position": "WR", "team": ""}])
    right = pd.DataFrame([
        {"player_name": "John Smith", "position": "WR", "team": "BUF"},
        {"player_name": "John Smith", "position": "WR", "team": "MIA"},
    ])
    matches, left_unmatched, right_unmatched = match_players(left, right)
    assert matches == []
    assert len(left_unmatched) == 1
    assert len(right_unmatched) == 2

