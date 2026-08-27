import pandas as pd

from src.data.loaders import generate_sample_players
from src.draft.simulator import simulate_availability


def test_simulation_probability_ranges_and_complements():
    players = generate_sample_players().head(80)
    result = simulate_availability(players, 11, 23, 16, simulations=250, seed=42)
    probabilities = result.probabilities
    assert result.picks_simulated == 12
    assert probabilities["prob_available_next_pick"].between(0, 1).all()
    assert probabilities["prob_drafted_before_next_pick"].between(0, 1).all()
    totals = probabilities["prob_available_next_pick"] + probabilities["prob_drafted_before_next_pick"]
    assert (totals.round(10) == 1.0).all()
    assert abs(sum(result.expected_by_position.values()) - 12) < 0.01


def test_no_intervening_picks_means_everyone_survives():
    players = generate_sample_players().head(20)
    result = simulate_availability(players, 23, 23, 16, simulations=10)
    assert (result.probabilities["prob_available_next_pick"] == 1.0).all()

