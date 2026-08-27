from src.draft.state import DraftState
from src.storage.database import Database


def test_sqlite_draft_round_trip_and_secret_rejection(tmp_path):
    database = Database(tmp_path / "test.db")
    state = DraftState(my_draft_position=1)
    state.draft_player({"player_id": "p1", "player_name": "Player", "position": "RB", "team": "BUF"})
    database.save_draft_state(state)
    restored = database.load_draft_state()
    assert restored is not None
    assert restored.history[0].player_id == "p1"
    assert restored.current_pick == 2

    try:
        database.set_setting("ESPN_S2", "must-not-store")
    except ValueError:
        pass
    else:
        raise AssertionError("secret setting should have been rejected")

