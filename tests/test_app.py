from app import app, dataframe_records, initial_state, render_page
from src.data.loaders import generate_sample_players


def test_dash_index_is_served():
    response = app.server.test_client().get("/")
    assert response.status_code == 200
    assert b"Fantasy Football War Room" in response.data


def test_dash_layout_and_initial_state():
    assert app.layout is not None
    state = initial_state()
    assert state["league_size"] == 16
    assert state["my_draft_position"] == 10


def test_draft_room_component_tree_renders():
    content, banner, message = render_page(
        "draft",
        initial_state(),
        dataframe_records(generate_sample_players()),
        None,
        {"league_id": None, "season": 2026, "simulation_count": 100},
        "Ready",
    )
    assert content is not None
    assert "16 teams" in banner
    assert message == "Ready"
