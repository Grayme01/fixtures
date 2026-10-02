import copy
from datetime import datetime, timezone

import pytest

from conftest import CALNAME, MATCH_URL_BASE, STRIP, TEAM
from diff_ics import MAX_BYTES, diff, parse_ics, summarise
from dribl_to_ics import build_calendar

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)  # before Coventry's Round 1


def _ics(fixtures: list[dict]) -> str:
    return build_calendar(fixtures, TEAM, CALNAME, MATCH_URL_BASE, strip_team_prefix=STRIP, duration_min=45)[0]


@pytest.fixture
def old(fixtures) -> str:
    return _ics(fixtures)


def _changed(fixtures: list[dict], i: int, **attrs) -> str:
    fixtures[i]["attributes"].update(attrs)
    return _ics(fixtures)


def test_initial_list(old):
    assert summarise("", old) == "Initial fixture list (3 fixtures)"


def test_dtstamp_only_change_is_silent(old):
    new = old.replace("DTSTAMP:2", "DTSTAMP:1")
    assert new != old
    assert summarise(old, new) == ""


def test_time_change(old, fixtures):
    new = _changed(fixtures, 0, date="2026-10-08T08:00:00.000000Z")
    assert diff(parse_ics(old), parse_ics(new), NOW) == (
        "~ Coventry City FC v Besiktas (Thu 8 Oct 7:00pm): time: Thu 8 Oct 8:00pm → Thu 8 Oct 7:00pm"
    )


def test_time_change_across_changeover(old, fixtures):
    # Same 7pm local kickoff, but a week earlier in AEST: 09:00 UTC, not 08:00.
    new = _changed(fixtures, 0, date="2026-10-01T09:00:00.000000Z")
    body = diff(parse_ics(old), parse_ics(new), datetime(2026, 9, 30, tzinfo=timezone.utc))
    assert body.endswith("time: Thu 8 Oct 8:00pm → Thu 1 Oct 7:00pm")


def test_ground_change(old, fixtures):
    new = _changed(fixtures, 1, field_name="Field 09")
    # Only the first LOCATION component is shown, so a field-only change
    # still notifies but reads as the same ground.
    assert diff(parse_ics(old), parse_ics(new), NOW) == (
        "~ Young Boys v Coventry City FC (Thu 15 Oct 8:00pm): "
        "ground: Tempe Recreation Reserve → Tempe Recreation Reserve"
    )


def test_added_and_removed(old, fixtures):
    new = _ics(fixtures[1:])  # Round 1 cancelled
    assert diff(parse_ics(old), parse_ics(new), NOW) == (
        "- Coventry City FC v Besiktas — Thu 8 Oct 8:00pm — @ Tempe Recreation Reserve"
    )
    assert diff(parse_ics(new), parse_ics(old), NOW) == (
        "+ Coventry City FC v Besiktas — Thu 8 Oct 8:00pm — @ Tempe Recreation Reserve"
    )


def test_past_fixtures_are_ignored(old, fixtures):
    new = _changed(fixtures, 0, home_score=2, away_score=2, field_name="Field 01")
    after_round_1 = datetime(2026, 10, 9, tzinfo=timezone.utc)
    assert diff(parse_ics(old), parse_ics(new), after_round_1) == ""
    assert diff(parse_ics(old), parse_ics(_ics(fixtures[1:])), after_round_1) == ""


def test_long_diff_is_truncated(fixture):
    many = []
    for i in range(80):
        f = copy.deepcopy(fixture)
        f["hash_id"] = f"uid{i:03d}"
        f["attributes"]["date"] = f"2026-11-{1 + i % 28:02d}T09:00:00.000000Z"
        many.append(f)
    body = diff({}, parse_ics(_ics(many)), NOW)
    assert len(body.encode("utf-8")) <= MAX_BYTES
    assert body.splitlines()[-1].startswith("… (+")
