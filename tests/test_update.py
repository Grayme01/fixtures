from datetime import datetime, timezone

import pytest

import update
from conftest import CALNAME, MATCH_URL_BASE, TEAM
from dribl_to_ics import build_calendar

COVENTRY = {"name": "Coventry", "tenant": "pAnmYMzmzG", "season": "XRNErWXKva", "match_url_base": MATCH_URL_BASE}


@pytest.fixture
def ics(fixtures) -> str:
    return build_calendar(fixtures, TEAM, CALNAME)[0]


def _season(is_current: bool):
    return lambda *a, **k: {"is_current": is_current}


def test_healthy_team_has_no_warnings(ics, monkeypatch):
    monkeypatch.setattr(update, "fetch_season", _season(True))
    assert update.health_warnings(COVENTRY, ics, datetime(2026, 10, 2, tzinfo=timezone.utc)) == []


def test_warns_when_no_future_fixtures(ics, monkeypatch):
    monkeypatch.setattr(update, "fetch_season", _season(True))
    warnings = update.health_warnings(COVENTRY, ics, datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert warnings == ["Coventry: no future fixtures left"]


def test_warns_when_season_not_current(ics, monkeypatch):
    monkeypatch.setattr(update, "fetch_season", _season(False))
    warnings = update.health_warnings(COVENTRY, ics, datetime(2026, 10, 2, tzinfo=timezone.utc))
    assert warnings == ["Coventry: season XRNErWXKva is no longer the current Dribl season"]


def test_season_lookup_failure_is_not_fatal(ics, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("dribl down")
    monkeypatch.setattr(update, "fetch_season", boom)
    assert update.health_warnings(COVENTRY, ics, datetime(2026, 10, 2, tzinfo=timezone.utc)) == []


@pytest.mark.parametrize("event, day, due", [
    ("workflow_dispatch", 2, True),
    ("schedule", 1, True),    # Thursday 1 Oct 2026
    ("schedule", 2, False),   # Friday
    ("push", 1, False),
])
def test_alert_due(event, day, due, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    assert update.alert_due(datetime(2026, 10, day, tzinfo=timezone.utc)) is due


def test_missing_secret_fails_fast(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC_HEARTBEAT", "hb")
    monkeypatch.delenv("NTFY_TOPIC_X", raising=False)
    with pytest.raises(SystemExit):
        update.load_secrets([{"ntfy_secret": "NTFY_TOPIC_X"}])


def test_archived_teams_are_configured_inactive():
    teams = {t["out"]: t["active"] for t in update.load_teams(update.ROOT / "teams.toml")}
    assert teams == {"marrickville_o45.ics": True, "burwood.ics": False,
                     "burwood_45_03.ics": False, "easts_pisa.ics": False}
