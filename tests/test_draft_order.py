import pytest

from src.draft.order import (
    get_next_pick_for_team,
    get_round_for_pick,
    get_team_draft_slots,
    get_team_for_pick,
)
from src.draft.state import DraftState


def test_team_ten_pick_sequence_in_sixteen_team_snake():
    assert get_team_draft_slots(10, 16, 7) == [10, 23, 42, 55, 74, 87, 106]


def test_snake_turn_boundaries():
    assert get_team_for_pick(16, 16) == 16
    assert get_team_for_pick(17, 16) == 16
    assert get_team_for_pick(32, 16) == 1
    assert get_team_for_pick(33, 16) == 1
    assert get_round_for_pick(33, 16) == 3


def test_next_pick_is_at_or_after_current_pick():
    assert get_next_pick_for_team(10, 10, 16, 15) == 10
    assert get_next_pick_for_team(11, 10, 16, 15) == 23
    assert get_next_pick_for_team(241, 10, 16, 15) is None


def test_invalid_team_rejected():
    with pytest.raises(ValueError):
        get_team_draft_slots(17, 16, 15)


def test_drafted_player_tracking_undo_and_correction():
    state = DraftState(league_size=16, rounds=15, my_draft_position=1)
    first = {"player_id": "p1", "player_name": "First Player", "position": "RB", "team": "BUF"}
    second = {"player_id": "p2", "player_name": "Second Player", "position": "WR", "team": "DET"}
    replacement = {"player_id": "p3", "player_name": "Replacement", "position": "TE", "team": "KC"}
    state.draft_player(first)
    state.draft_player(second)
    assert state.current_pick == 3
    assert state.drafted_player_ids == {"p1", "p2"}
    state.correct_pick(1, replacement)
    assert state.history[0].player_id == "p3"
    undone = state.undo_last_pick()
    assert undone and undone.player_id == "p2"
    assert state.current_pick == 2


def test_state_serialization_contains_no_credentials():
    payload = DraftState().to_dict()
    serialized = str(payload).lower()
    assert "espn_s2" not in serialized
    assert "swid" not in serialized

