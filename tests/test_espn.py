from types import SimpleNamespace

import pytest

from src.integrations.espn import ESPNClient, ESPNConnectionError, ESPNCredentials
from src.draft.espn_sync import apply_normalized_draft_picks
from src.draft.state import DraftState


def player(player_id=1, name="Mock Runner", position="RB"):
    return SimpleNamespace(
        playerId=player_id,
        name=name,
        position=position,
        proTeam="BUF",
        injuryStatus="ACTIVE",
        posRank=3,
        projected_total_points=210.5,
        total_points=0,
        percent_owned=98.2,
        acquisitionType="DRAFT",
        lineupSlot="RB",
    )


def mock_league():
    roster_player = player()
    team = SimpleNamespace(
        team_id=7,
        team_name="Mock Team",
        owners=[{"displayName": "Manager One"}],
        wins=0,
        losses=0,
        ties=0,
        standing=None,
        points_for=0,
        points_against=0,
        roster=[roster_player],
    )
    settings = SimpleNamespace(
        name="Mock Public League",
        team_count=16,
        scoring_format="standard",
        roster_settings={"lineupSlotCounts": {"QB": 1, "RB": 2, "WR": 2, "BE": 6}},
        draft_settings={"rounds": 15},
    )
    league = SimpleNamespace(settings=settings, teams=[team], draft=[], current_week=1)
    league.free_agents = lambda size=500: [player(2, "Mock Receiver", "WR")]
    league.scoreboard = lambda: []
    return league


def test_public_league_response_parsing():
    credentials = ESPNCredentials(league_id=123, season=2026)
    snapshot = ESPNClient.normalize_league(mock_league(), credentials)
    assert snapshot.league.name == "Mock Public League"
    assert snapshot.league.team_count == 16
    assert len(snapshot.players) == 2
    assert snapshot.teams.iloc[0]["team_name"] == "Mock Team"


def test_team_and_roster_parsing():
    snapshot = ESPNClient.normalize_league(mock_league(), ESPNCredentials(123))
    assert snapshot.teams.iloc[0]["owner"] == "Manager One"
    assert snapshot.rosters.iloc[0]["player_name"] == "Mock Runner"
    assert snapshot.rosters.iloc[0]["team_id"] == 7


def test_private_league_configuration_passes_both_cookies():
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return mock_league()

    credentials = ESPNCredentials(123, 2026, espn_s2="secret-token", swid="{guid}")
    ESPNClient(credentials, league_factory=factory).connect()
    assert captured["espn_s2"] == "secret-token"
    assert captured["swid"] == "{guid}"
    assert captured["debug"] is False


def test_missing_league_id_fails_safely():
    with pytest.raises(ESPNConnectionError, match="league ID"):
        ESPNClient(ESPNCredentials(None)).connect()


def test_partial_private_credentials_rejected():
    with pytest.raises(ESPNConnectionError, match="both"):
        ESPNCredentials(123, espn_s2="one-only").validate()


def test_invalid_espn_response_becomes_safe_error():
    def broken_factory(**kwargs):
        raise RuntimeError("401 unauthorized with internal details")

    with pytest.raises(ESPNConnectionError, match="league is private") as error:
        ESPNClient(ESPNCredentials(123), league_factory=broken_factory).connect()
    assert "internal details" not in str(error.value)


def test_private_league_without_cookies_has_actionable_error():
    class ESPNAccessDenied(Exception):
        pass

    def private_league(**kwargs):
        raise ESPNAccessDenied("espn_s2 and swid are required")

    with pytest.raises(ESPNConnectionError, match="league is private") as error:
        ESPNClient(ESPNCredentials(123), league_factory=private_league).connect()
    assert "local .env file" in str(error.value)


def test_rejected_private_credentials_are_distinguished_from_missing_cookies():
    class ESPNAccessDenied(Exception):
        pass

    def rejected_credentials(**kwargs):
        raise ESPNAccessDenied("Access denied")

    credentials = ESPNCredentials(123, espn_s2="expired", swid="{expired}")
    with pytest.raises(ESPNConnectionError, match="rejected the private-league credentials"):
        ESPNClient(credentials, league_factory=rejected_credentials).connect()


def test_normalized_espn_draft_import_and_manual_history_protection():
    players = ESPNClient.normalize_players([player()])
    picks = __import__("pandas").DataFrame([
        {"overall_pick": 1, "player_id": "1", "player_name": "Mock Runner"}
    ])
    state = DraftState()
    imported, warnings = apply_normalized_draft_picks(state, picks, players)
    assert imported == 1
    assert not warnings
    assert state.history[0].player_name == "Mock Runner"
    imported_again, warnings = apply_normalized_draft_picks(state, picks, players)
    assert imported_again == 0
    assert "preserved" in warnings[0]
