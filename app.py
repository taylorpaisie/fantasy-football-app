"""Dash entry point for the Fantasy Football War Room."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import yaml
from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html, no_update
from dotenv import load_dotenv

from src.data.loaders import generate_sample_players
from src.draft.espn_sync import apply_normalized_draft_picks
from src.draft.order import get_next_pick_for_team, get_round_for_pick, get_team_for_pick
from src.draft.simulator import SimulationResult, simulate_availability
from src.draft.state import DraftState
from src.integrations.espn import ESPNClient, ESPNConnectionError, ESPNCredentials
from src.recommendations.engine import espn_value_gaps, recommend_players
from src.recommendations.scarcity import calculate_positional_scarcity
from src.storage.database import Database

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
with (ROOT / "config" / "league_config.yaml").open(encoding="utf-8") as handle:
    CONFIG: dict[str, Any] = yaml.safe_load(handle)

DATABASE = Database(ROOT / "data" / "fantasy_war_room.db")
CARD = {"background": "#17202b", "border": "1px solid #303b49", "borderRadius": "10px", "padding": "16px"}
MUTED = {"color": "#9aa7b5"}
BUTTON = {"padding": "9px 16px", "border": 0, "borderRadius": "7px", "cursor": "pointer", "fontWeight": 700}
TAB_STYLE = {
    "backgroundColor": "#161b22",
    "color": "#000000",
    "border": "1px solid #30363d",
    "borderBottom": "1px solid #30363d",
    "padding": "12px 10px",
    "fontWeight": 600,
}
SELECTED_TAB_STYLE = {
    **TAB_STYLE,
    "backgroundColor": "#1f6feb",
    "color": "#ffffff",
    "borderTop": "3px solid #79c0ff",
    "borderBottom": "1px solid #1f6feb",
    "fontWeight": 800,
}


def dataframe_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return JSON-safe records for Dash stores and tables."""
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def initial_state() -> dict[str, Any]:
    return DraftState(
        league_size=int(CONFIG["league_size"]),
        rounds=int(CONFIG["rounds"]),
        my_draft_position=int(CONFIG["draft_position"]),
    ).to_dict()


def prepare_espn_players(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.drop_duplicates("player_id", keep="first").reset_index(drop=True).copy()
    if result.empty:
        return result
    projected = pd.to_numeric(result["projected_points"], errors="coerce")
    espn_rank = pd.to_numeric(result["espn_rank"], errors="coerce")
    projection_rank = projected.rank(method="min", ascending=False)
    fallback = pd.Series(range(1, len(result) + 1), index=result.index, dtype=float)
    result["espn_rank"] = espn_rank.fillna(projection_rank).fillna(fallback)
    result["model_rank"] = projection_rank.fillna(result["espn_rank"]).fillna(fallback)
    result["consensus_rank"] = pd.to_numeric(result["consensus_rank"], errors="coerce").fillna(result["model_rank"])
    result["adp"] = pd.to_numeric(result["adp"], errors="coerce").fillna(result["espn_rank"])
    rank_proxy = 260 - result["model_rank"].clip(upper=250) * 0.65
    result["projected_points"] = projected.fillna(rank_proxy.clip(lower=50))
    result["position_rank"] = result.groupby("position")["model_rank"].rank(method="min")
    result["tier"] = ((result["position_rank"] - 1) // 8 + 1).astype(int)
    return result


def active_roster_requirements(snapshot: dict[str, Any] | None) -> dict[str, int]:
    base = {str(key): int(value) for key, value in CONFIG["roster"].items()}
    slots = ((snapshot or {}).get("league") or {}).get("roster_slots") or {}
    aliases = {"DST": "D/ST", "DEF": "D/ST", "BE": "BENCH", "BN": "BENCH",
               "RB/WR/TE": "FLEX", "WR/RB": "FLEX"}
    actual: dict[str, int] = {}
    for raw_slot, count in slots.items():
        slot = aliases.get(str(raw_slot).upper(), str(raw_slot).upper())
        if slot in {"QB", "RB", "WR", "TE", "FLEX", "D/ST", "K", "BENCH"}:
            actual[slot] = int(count)
    return actual if {"QB", "RB", "WR", "TE"}.intersection(actual) else base


def snapshot_to_dict(snapshot: Any) -> dict[str, Any]:
    return {
        "league": snapshot.league.to_dict(),
        "teams": dataframe_records(snapshot.teams),
        "rosters": dataframe_records(snapshot.rosters),
        "players": dataframe_records(snapshot.players),
        "draft_picks": dataframe_records(snapshot.draft_picks),
        "matchups": dataframe_records(snapshot.matchups),
        "warnings": snapshot.warnings,
    }


@lru_cache(maxsize=64)
def forecast_cached(
    player_json: str, state_json: str, settings_json: str, snapshot_json: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float], int | None, int, int | None, bool]:
    players = pd.DataFrame(json.loads(player_json))
    state = DraftState.from_dict(json.loads(state_json))
    settings = json.loads(settings_json)
    snapshot = json.loads(snapshot_json) if snapshot_json else None
    players["drafted"] = players["player_id"].astype(str).isin(state.drafted_player_ids)
    available = players[~players["drafted"]].copy()
    current_team = None if state.is_complete else get_team_for_pick(state.current_pick, state.league_size)
    my_turn = current_team == state.my_draft_position
    target = get_next_pick_for_team(
        state.current_pick + (1 if my_turn else 0), state.my_draft_position,
        state.league_size, state.rounds,
    ) if not state.is_complete else None
    first_pick = state.current_pick + (1 if my_turn else 0)
    if target is None:
        probability = available[["player_id"]].copy()
        probability["prob_available_next_pick"] = 1.0
        probability["prob_drafted_before_next_pick"] = 0.0
        simulation = SimulationResult(probability, {}, 0)
    else:
        history = [{"team_number": pick.team_number, "position": pick.position} for pick in state.history]
        simulation = simulate_availability(
            available, first_pick, target, state.league_size,
            simulations=int(settings["simulation_count"]), history=history,
            weights=CONFIG["simulation_weights"],
            seed=int(CONFIG.get("simulation_seed", 2026)) + state.current_pick,
        )
    scarcity = calculate_positional_scarcity(available, simulation.expected_by_position, state.league_size)
    recommendations = recommend_players(
        available, simulation.probabilities, scarcity, state.my_roster,
        active_roster_requirements(snapshot), CONFIG["recommendation_weights"],
        get_round_for_pick(min(state.current_pick, state.total_picks), state.league_size),
        CONFIG.get("strategy", {}),
    )
    return (
        dataframe_records(recommendations), dataframe_records(scarcity),
        simulation.expected_by_position, target, simulation.picks_simulated, current_team, my_turn,
    )


def forecast(player_data: list[dict[str, Any]], state_data: dict[str, Any], settings: dict[str, Any], snapshot: Any):
    return forecast_cached(
        json.dumps(player_data, sort_keys=True), json.dumps(state_data, sort_keys=True),
        json.dumps(settings, sort_keys=True), json.dumps(snapshot, sort_keys=True) if snapshot else "",
    )


def metric(label: str, value: Any) -> html.Div:
    return html.Div([html.Div(label, style=MUTED), html.Div(str(value), style={"fontSize": "26px", "fontWeight": 800})], style=CARD)


def table(frame: pd.DataFrame, page_size: int = 20, table_id: str | None = None) -> dash_table.DataTable:
    properties: dict[str, Any] = dict(
        data=dataframe_records(frame),
        columns=[{"name": str(column), "id": str(column)} for column in frame.columns],
        sort_action="native", filter_action="native", page_action="native", page_size=page_size,
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#17202b", "color": "white", "fontWeight": "bold"},
        style_cell={"backgroundColor": "#0f151c", "color": "#e8edf2", "border": "1px solid #303b49",
                    "padding": "8px", "textAlign": "left", "fontFamily": "Arial", "minWidth": "85px"},
    )
    if table_id is not None:
        properties["id"] = table_id
    return dash_table.DataTable(**properties)


def recommendation_card(recommendations: pd.DataFrame, target: int | None) -> html.Div:
    if recommendations.empty:
        return html.Div("No players remain.", style=CARD)
    best = recommendations.iloc[0]
    alternatives = recommendations.iloc[1:5]["player_name"].tolist()
    return html.Div([
        html.Div("BEST AVAILABLE DECISION", style={"fontWeight": 800, "color": "#58a6ff"}),
        html.H2(best["player_name"], style={"marginBottom": "2px"}),
        html.Div(f"{best['position']} — {best['team']}", style=MUTED),
        html.Div([metric("Recommendation score", f"{best['recommendation_score']:.0f}/100"),
                  metric(f"Chance available at #{target}" if target else "Future availability",
                         f"{best['prob_available_next_pick']:.0%}")],
                 style={"display": "grid", "gridTemplateColumns": "repeat(2,minmax(180px,1fr))", "gap": "12px", "margin": "14px 0"}),
        html.H4("Why"), html.Ul([html.Li(reason) for reason in best["reasons"]]),
        html.Div("Alternatives: " + " · ".join(f"{i}. {name}" for i, name in enumerate(alternatives, 1)), style=MUTED),
    ], style={**CARD, "borderLeft": "5px solid #2ea043"})


def draft_page(player_data, state_data, settings, snapshot) -> html.Div:
    rec_data, scarcity_data, expected, target, picks_between, current_team, my_turn = forecast(
        player_data, state_data, settings, snapshot
    )
    recs, scarcity = pd.DataFrame(rec_data), pd.DataFrame(scarcity_data)
    state = DraftState.from_dict(state_data)
    options = [{"label": f"{row.player_name} — {row.position} ({row.team})", "value": str(row.player_id)} for row in recs.itertuples()]
    history = pd.DataFrame([{"Pick": p.overall_pick, "Round": p.round_number, "Slot": p.team_number,
                             "Player": p.player_name, "Position": p.position} for p in reversed(state.history)])
    display = recs.rename(columns={"player_name": "Player", "position": "Pos", "team": "Team", "espn_rank": "ESPN Rank",
        "adp": "ADP", "model_rank": "Model Rank", "projected_points": "Proj", "tier": "Tier",
        "prob_available_next_pick": "P(next)", "recommendation_score": "Rec Score", "recommendation_rank": "Rec Rank"})
    display_columns = ["Player", "Pos", "Team", "ESPN Rank", "ADP", "Model Rank", "Proj", "Tier", "P(next)", "Rec Score", "Rec Rank", "player_id"]
    display = display[[column for column in display_columns if column in display]]
    pressure_fig = px.bar(scarcity[scarcity["position"].isin(["RB", "WR", "QB", "TE"])],
                          x="position", y="scarcity_score", color="status", template="plotly_dark")
    return html.Div([
        html.Div([metric("Current pick", "Complete" if state.is_complete else f"#{state.current_pick}"),
                  metric("Round", min(get_round_for_pick(max(1, state.current_pick), state.league_size), state.rounds)),
                  metric("Drafting team", "—" if current_team is None else f"Slot {current_team}"),
                  metric("My next pick", f"#{target}" if target else "—"), metric("Picks before then", picks_between)],
                 style={"display": "grid", "gridTemplateColumns": "repeat(5,minmax(130px,1fr))", "gap": "12px"}),
        html.Div("YOUR PICK" if my_turn else f"Slot {current_team} is on the clock" if current_team else "Draft complete",
                 style={"margin": "18px 0 8px", "fontWeight": 800, "color": "#3fb950" if my_turn else "#d2a8ff"}),
        recommendation_card(recs, target) if my_turn else html.Div(),
        html.H3("Fast pick entry"),
        html.Div([dcc.Input(id="player-search", placeholder="Search player…", debounce=True, style={"padding": "10px", "width": "100%"}),
                  dcc.Dropdown(id="position-filter", options=["ALL", "RB", "WR", "TE", "QB", "D/ST", "K"], value="ALL", clearable=False),
                  dcc.Dropdown(id="player-select", options=options, placeholder="Select player…"),
                  html.Button("DRAFT", id="draft-btn", n_clicks=0, style={**BUTTON, "background": "#238636", "color": "white"})],
                 style={"display": "grid", "gridTemplateColumns": "2fr 1fr 3fr 1fr", "gap": "10px"}),
        html.Div(table(display.head(180), 25, "player-table"), style={"marginTop": "14px"}),
        html.Div([html.Div([html.H3("Position pressure"), dcc.Graph(figure=pressure_fig, config={"displayModeBar": False}),
                           table(scarcity.rename(columns={"position": "Position", "expected_drafted": "Expected gone",
                                                          "tier_drop": "Tier drop", "status": "Status"}), 10)], style=CARD),
                  html.Div([html.H3("My roster"),
                            table(pd.DataFrame([{"Player": p.player_name, "Pos": p.position, "Pick": p.overall_pick}
                                                for p in state.my_roster]), 20) if state.my_roster else html.Div("No players yet.", style=MUTED),
                            html.H3("Next-pick forecast"),
                            table(pd.DataFrame([{"Position": pos, "Expected drafted": round(value, 1)}
                                                for pos, value in expected.items()]), 10)], style=CARD)],
                 style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "14px", "marginTop": "14px"}),
        html.H3("Draft controls"),
        html.Div([html.Button("Undo Last Pick", id="undo-btn", n_clicks=0, style=BUTTON),
                  html.Button("Save Draft", id="save-btn", n_clicks=0, style=BUTTON),
                  html.Button("Load Saved Draft", id="load-btn", n_clicks=0, style=BUTTON)], style={"display": "flex", "gap": "10px"}),
        html.Details([html.Summary("Correct a mistaken pick"),
                      dcc.Dropdown(id="correct-pick", options=[{"label": f"#{p.overall_pick} {p.player_name}", "value": p.overall_pick} for p in state.history], placeholder="Pick"),
                      dcc.Dropdown(id="replacement-player", options=options, placeholder="Replacement player"),
                      html.Button("Apply correction", id="correct-btn", n_clicks=0, style=BUTTON)], style={"marginTop": "14px"}),
        html.Details([html.Summary("Reset draft"),
                      dcc.Checklist(id="reset-confirm", options=[{"label": " Confirm reset", "value": "yes"}], value=[]),
                      html.Button("Reset Draft", id="reset-btn", n_clicks=0, style={**BUTTON, "background": "#da3633", "color": "white"})], style={"marginTop": "10px"}),
        html.H3("Draft history"), table(history, 20) if not history.empty else html.Div("No picks recorded.", style=MUTED),
    ])


def settings_page(settings, snapshot, state_data) -> html.Div:
    state = DraftState.from_dict(state_data)
    team_options = [{"label": f"{row.get('team_name')} — {row.get('owner') or 'owner unavailable'}", "value": row.get("team_id")}
                    for row in (snapshot or {}).get("teams", [])]
    return html.Div([
        html.H2("ESPN Connection"),
        html.Div("● Connected" if snapshot else "● Not connected",
                 style={"color": "#3fb950" if snapshot else "#f85149", "fontWeight": 800}),
        html.Label("League ID"), dcc.Input(id="league-id", type="number", value=settings.get("league_id"), style={"display": "block", "padding": "9px", "width": "320px"}),
        html.Label("Season"), dcc.Input(id="season", type="number", value=settings.get("season", 2026), style={"display": "block", "padding": "9px", "width": "320px"}),
        html.Label("Monte Carlo simulations"), dcc.Input(id="simulation-count", type="number", min=100, max=20000, step=100,
                                                          value=settings.get("simulation_count", 5000), style={"display": "block", "padding": "9px", "width": "320px"}),
        html.Div("Private credentials detected" if os.getenv("ESPN_S2") and os.getenv("ESPN_SWID") else "Public-league mode",
                 style={**MUTED, "margin": "12px 0"}),
        html.Button("Test ESPN Connection", id="test-espn-btn", n_clicks=0, style={**BUTTON, "background": "#1f6feb", "color": "white"}),
        html.Button("Refresh League Data", id="refresh-espn-btn", n_clicks=0, style={**BUTTON, "marginLeft": "10px"}),
        html.H3("My ESPN team"),
        dcc.Dropdown(id="espn-team-select", options=team_options, value=state.selected_espn_team_id,
                     placeholder="Select by team/owner", style={"maxWidth": "600px"}),
        html.Button("Save My Team", id="save-team-btn", n_clicks=0, style={**BUTTON, "marginTop": "8px"}),
        html.H3("Completed ESPN draft"),
        html.Button("Import ESPN Draft Picks", id="import-draft-btn", n_clicks=0,
                    disabled=not bool((snapshot or {}).get("draft_picks")) or bool(state.history), style=BUTTON),
        html.P("Existing manual history is never overwritten. ESPN live-draft availability is best-effort; manual mode remains authoritative.", style=MUTED),
        html.Pre(json.dumps((snapshot or {}).get("league", {}), indent=2), style={**CARD, "overflowX": "auto"}) if snapshot else html.Div(),
    ], style={"maxWidth": "900px"})


def league_page(snapshot) -> html.Div:
    if not snapshot:
        return html.Div([html.H2("League"), html.P("Connect ESPN in Settings. Offline draft mode remains available.")])
    info = snapshot["league"]
    return html.Div([html.H2(info.get("name", "ESPN League")), html.P("ESPN Fantasy Football", style=MUTED),
                     html.Div([metric("Teams", info.get("team_count")), metric("Scoring", info.get("scoring_type")),
                               metric("Season", info.get("season")), metric("Week", info.get("current_week") or "Preseason")],
                              style={"display": "grid", "gridTemplateColumns": "repeat(4,1fr)", "gap": "12px"}),
                     html.H3("Standings"), table(pd.DataFrame(snapshot.get("teams", [])), 20),
                     html.H3("Matchups"), table(pd.DataFrame(snapshot.get("matchups", [])), 20)])


def team_page(snapshot, state_data) -> html.Div:
    state = DraftState.from_dict(state_data)
    if snapshot and state.selected_espn_team_id is not None:
        rosters = pd.DataFrame(snapshot.get("rosters", []))
        roster = rosters[rosters["team_id"] == state.selected_espn_team_id] if not rosters.empty else rosters
        return html.Div([html.H2("My Team"), table(roster, 25)])
    manual = pd.DataFrame([{"Player": p.player_name, "Position": p.position, "NFL Team": p.nfl_team, "Pick": p.overall_pick} for p in state.my_roster])
    return html.Div([html.H2("My Team"), html.P("Manual draft roster; ESPN team ID remains separate from draft slot.", style=MUTED), table(manual, 25)])


def value_gap_page(player_data) -> html.Div:
    players = pd.DataFrame(player_data)
    gaps = espn_value_gaps(players)
    chart = px.scatter(players, x="adp", y="projected_points", color="position", hover_name="player_name", template="plotly_dark")
    return html.Div([html.H2("ESPN Value Gap"),
                     html.P("Positive = model rank is better than ESPN rank, suggesting a possible platform value.", style=MUTED),
                     table(gaps.rename(columns={"player_name": "Player", "position": "Position", "espn_rank": "ESPN Rank",
                                                        "model_rank": "Model Rank", "difference": "Difference",
                                                        "interpretation": "Interpretation"}), 25), dcc.Graph(figure=chart)])


app = Dash(__name__, suppress_callback_exceptions=True, title="Fantasy Football War Room")
server = app.server
app.layout = html.Div([
    dcc.Store(id="draft-store", storage_type="session", data=initial_state()),
    dcc.Store(id="player-store", storage_type="session", data=dataframe_records(generate_sample_players())),
    dcc.Store(id="espn-store", storage_type="session"),
    dcc.Store(id="source-store", storage_type="session", data="Synthetic sample data (offline mode)"),
    dcc.Store(id="settings-store", storage_type="local", data={
        "league_id": int(os.getenv("ESPN_LEAGUE_ID")) if os.getenv("ESPN_LEAGUE_ID", "").isdigit() else DATABASE.get_setting("espn_league_id"),
        "season": int(os.getenv("ESPN_SEASON", CONFIG["season"])), "simulation_count": int(CONFIG["simulation_count"]),
    }),
    dcc.Store(id="message-store", data="Ready in offline/manual mode."),
    html.Header([html.H1("🏈 Fantasy Football War Room", style={"margin": 0}), html.Div(id="connection-banner", style=MUTED)],
                style={"padding": "22px 4vw", "borderBottom": "1px solid #303b49"}),
    dcc.Tabs(
        id="navigation",
        value="draft",
        parent_style={"backgroundColor": "#161b22", "borderBottom": "1px solid #30363d"},
        children=[
            dcc.Tab(label="Draft Room", value="draft", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="League", value="league", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="My Team", value="team", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="ESPN Value Gap", value="gaps", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="Waivers", value="waivers", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="Start / Sit", value="lineup", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="Trades", value="trades", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="News & Injuries", value="injuries", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="Matchups", value="matchups", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
            dcc.Tab(label="Settings", value="settings", style=TAB_STYLE, selected_style=SELECTED_TAB_STYLE),
        ],
    ),
    html.Div(id="action-message", style={"margin": "12px 4vw", "color": "#58a6ff"}),
    html.Main(id="page-content", style={"padding": "10px 4vw 50px"}),
], style={"background": "#0d1117", "color": "#e8edf2", "minHeight": "100vh", "fontFamily": "Arial, sans-serif"})


@app.callback(
    Output("page-content", "children"), Output("connection-banner", "children"), Output("action-message", "children"),
    Input("navigation", "value"), Input("draft-store", "data"), Input("player-store", "data"),
    Input("espn-store", "data"), Input("settings-store", "data"), Input("message-store", "data"))
def render_page(page, state_data, player_data, snapshot, settings, message):
    state = DraftState.from_dict(state_data)
    banner = f"ESPN: {'● Connected' if snapshot else '○ Offline/manual'} · {state.league_size} teams · Draft slot #{state.my_draft_position}"
    if page == "draft":
        content = draft_page(player_data, state_data, settings, snapshot)
    elif page == "league":
        content = league_page(snapshot)
    elif page == "team":
        content = team_page(snapshot, state_data)
    elif page == "gaps":
        content = value_gap_page(player_data)
    elif page == "settings":
        content = settings_page(settings, snapshot, state_data)
    else:
        label = {"waivers": "Waivers", "lineup": "Start / Sit", "trades": "Trades",
                 "injuries": "News & Injuries", "matchups": "Matchups"}[page]
        content = html.Div([html.H2(label), html.P(f"{label} is connected to the normalized season-mode architecture; full analytics follow draft validation.")])
    return content, banner, message


@app.callback(
    Output("player-select", "options"), Output("player-table", "data"),
    Input("player-search", "value"), Input("position-filter", "value"),
    State("player-store", "data"), State("draft-store", "data"), State("settings-store", "data"), State("espn-store", "data"),
    prevent_initial_call=True)
def filter_players(search, position, player_data, state_data, settings, snapshot):
    rec_data, *_ = forecast(player_data, state_data, settings, snapshot)
    recs = pd.DataFrame(rec_data)
    if search:
        recs = recs[recs["player_name"].str.contains(str(search), case=False, na=False)]
    if position and position != "ALL":
        recs = recs[recs["position"] == position]
    options = [{"label": f"{row.player_name} — {row.position} ({row.team})", "value": str(row.player_id)} for row in recs.itertuples()]
    display = recs.rename(columns={"player_name": "Player", "position": "Pos", "team": "Team", "espn_rank": "ESPN Rank",
        "adp": "ADP", "model_rank": "Model Rank", "projected_points": "Proj", "tier": "Tier",
        "prob_available_next_pick": "P(next)", "recommendation_score": "Rec Score", "recommendation_rank": "Rec Rank"})
    columns = ["Player", "Pos", "Team", "ESPN Rank", "ADP", "Model Rank", "Proj", "Tier", "P(next)", "Rec Score", "Rec Rank", "player_id"]
    return options, dataframe_records(display[[column for column in columns if column in display]].head(180))


@app.callback(
    Output("draft-store", "data"), Output("message-store", "data"),
    Input("draft-btn", "n_clicks"), Input("undo-btn", "n_clicks"), Input("save-btn", "n_clicks"),
    Input("load-btn", "n_clicks"), Input("correct-btn", "n_clicks"), Input("reset-btn", "n_clicks"),
    State("player-select", "value"), State("correct-pick", "value"), State("replacement-player", "value"),
    State("reset-confirm", "value"), State("draft-store", "data"), State("player-store", "data"), prevent_initial_call=True)
def change_draft(_draft, _undo, _save, _load, _correct, _reset, selected, pick_number, replacement,
                 reset_confirm, state_data, player_data):
    state, players, trigger = DraftState.from_dict(state_data), pd.DataFrame(player_data), ctx.triggered_id
    try:
        if trigger == "draft-btn":
            if not selected:
                return no_update, "Select a player first."
            pick = state.draft_player(players[players["player_id"].astype(str) == str(selected)].iloc[0].to_dict())
            message = f"Recorded #{pick.overall_pick}: {pick.player_name} to slot {pick.team_number}."
        elif trigger == "undo-btn":
            pick = state.undo_last_pick()
            message = f"Undid {pick.player_name}." if pick else "Nothing to undo."
        elif trigger == "save-btn":
            DATABASE.save_draft_state(state)
            return no_update, "Draft saved locally to SQLite."
        elif trigger == "load-btn":
            loaded = DATABASE.load_draft_state()
            return (loaded.to_dict(), "Saved draft loaded.") if loaded else (no_update, "No saved draft found.")
        elif trigger == "correct-btn":
            if pick_number is None or not replacement:
                return no_update, "Choose a pick and replacement player."
            row = players[players["player_id"].astype(str) == str(replacement)].iloc[0].to_dict()
            state.correct_pick(int(pick_number), row)
            message = f"Corrected pick #{pick_number}."
        elif trigger == "reset-btn":
            if "yes" not in (reset_confirm or []):
                return no_update, "Confirm reset first."
            state.reset()
            message = "Draft reset."
        else:
            return no_update, no_update
        forecast_cached.cache_clear()
        return state.to_dict(), message
    except (ValueError, IndexError) as exc:
        return no_update, str(exc)


@app.callback(
    Output("espn-store", "data"), Output("player-store", "data", allow_duplicate=True),
    Output("source-store", "data"), Output("settings-store", "data", allow_duplicate=True),
    Output("draft-store", "data", allow_duplicate=True), Output("message-store", "data", allow_duplicate=True),
    Input("test-espn-btn", "n_clicks"), Input("refresh-espn-btn", "n_clicks"),
    State("league-id", "value"), State("season", "value"), State("simulation-count", "value"),
    State("settings-store", "data"), State("draft-store", "data"), State("player-store", "data"), prevent_initial_call=True)
def connect_espn(_test, _refresh, league_id, season, simulation_count, settings, state_data, player_data):
    settings = {**settings, "league_id": league_id, "season": int(season or 2026),
                "simulation_count": int(simulation_count or 5000)}
    credentials = ESPNCredentials(int(league_id) if league_id else None, int(season or 2026),
                                  os.getenv("ESPN_S2") or None, os.getenv("ESPN_SWID") or None)
    try:
        snapshot_obj = ESPNClient(credentials).fetch_snapshot()
        snapshot, state = snapshot_to_dict(snapshot_obj), DraftState.from_dict(state_data)
        if not state.history:
            state.league_size, state.rounds = snapshot_obj.league.team_count, snapshot_obj.league.draft_rounds
        players = prepare_espn_players(snapshot_obj.players) if len(snapshot_obj.players) >= 25 else pd.DataFrame(player_data)
        DATABASE.set_setting("espn_league_id", league_id)
        DATABASE.set_setting("espn_season", int(season))
        DATABASE.save_league_snapshot(snapshot_obj.league.to_dict(), snapshot_obj.teams.to_dict("records"))
        forecast_cached.cache_clear()
        warnings = " ".join(snapshot_obj.warnings)
        return snapshot, dataframe_records(players), "ESPN player metadata", settings, state.to_dict(), f"Connected to {snapshot_obj.league.name}. {warnings}".strip()
    except ESPNConnectionError as exc:
        return no_update, no_update, no_update, settings, no_update, f"ESPN connection failed: {exc} Manual mode remains available."
    except Exception:
        return no_update, no_update, no_update, settings, no_update, "ESPN returned an unexpected response. Manual mode remains available."


@app.callback(
    Output("draft-store", "data", allow_duplicate=True), Output("message-store", "data", allow_duplicate=True),
    Input("save-team-btn", "n_clicks"), State("espn-team-select", "value"), State("draft-store", "data"), prevent_initial_call=True)
def save_espn_team(_clicks, team_id, state_data):
    if team_id is None:
        return no_update, "Select an ESPN team first."
    state = DraftState.from_dict(state_data)
    state.selected_espn_team_id = int(team_id)
    DATABASE.set_setting("selected_espn_team_id", int(team_id))
    return state.to_dict(), "ESPN team saved separately from draft slot."


@app.callback(
    Output("draft-store", "data", allow_duplicate=True), Output("message-store", "data", allow_duplicate=True),
    Input("import-draft-btn", "n_clicks"), State("espn-store", "data"), State("draft-store", "data"), prevent_initial_call=True)
def import_espn_draft(_clicks, snapshot, state_data):
    if not snapshot:
        return no_update, "Connect ESPN first."
    state = DraftState.from_dict(state_data)
    imported, warnings = apply_normalized_draft_picks(
        state, pd.DataFrame(snapshot.get("draft_picks", [])), pd.DataFrame(snapshot.get("players", [])))
    forecast_cached.cache_clear()
    return state.to_dict(), f"Imported {imported} ESPN picks. {' '.join(warnings)}".strip()


if __name__ == "__main__":
    debug = os.getenv("DASH_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="127.0.0.1", port=8050)
