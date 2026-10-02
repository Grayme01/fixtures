from conftest import CALNAME, DATA, MATCH_URL_BASE, STRIP, TEAM
from diff_ics import _fmt_dt, parse_ics
from dribl_to_ics import build_calendar, build_event, origin_from


def _no_dtstamp(text: str) -> list[str]:
    return [line for line in text.split("\r\n") if not line.startswith("DTSTAMP")]


def _event(fixture: dict, **kwargs) -> dict[str, str]:
    return next(iter(parse_ics(build_event(fixture, TEAM, MATCH_URL_BASE, **kwargs)).values()))


def test_calendar_matches_published_file(fixtures):
    """Regression guard: same output, byte for byte bar DTSTAMP, as the
    marrickville_o45.ics published on 02-10-2026."""
    ics, n = build_calendar(fixtures, TEAM, CALNAME, MATCH_URL_BASE, strip_team_prefix=STRIP, duration_min=45)
    expected = (DATA / "expected_marrickville_o45.ics").read_bytes().decode()  # keep CRLFs
    assert n == 3
    assert _no_dtstamp(ics) == _no_dtstamp(expected)


def test_filters_to_team_and_drops_byes(fixtures):
    _, n_all = build_calendar(fixtures, None, CALNAME)
    _, n_team = build_calendar(fixtures, TEAM, CALNAME)
    assert (n_all, n_team) == (4, 3)  # 5 fixtures, one a bye


def test_strip_prefix_and_duration(fixture):
    ev = _event(fixture, strip_team_prefix=STRIP, duration_min=45)
    assert ev["SUMMARY"] == "Coventry City FC v Besiktas"
    assert (ev["DTSTART"], ev["DTEND"]) == ("20261008T090000Z", "20261008T094500Z")


def test_default_duration_is_90(fixture):
    assert _event(fixture)["DTEND"] == "20261008T103000Z"


def test_home_away_prefix(fixtures):
    home, away = fixtures[0], fixtures[1]  # Coventry home in R1, away in R2
    assert _event(home, home_prefix="H ", away_prefix="A ", strip_team_prefix=STRIP)["SUMMARY"].startswith("H Coventry")
    assert _event(away, home_prefix="H ", away_prefix="A ", strip_team_prefix=STRIP)["SUMMARY"].startswith("A Young Boys")


def test_score_appended_once_played(fixture):
    fixture["attributes"].update(home_score=3, away_score=1)
    assert _event(fixture, strip_team_prefix=STRIP)["SUMMARY"] == "Coventry City FC v Besiktas (3-1)"


def test_location_and_match_link(fixture):
    ev = _event(fixture)
    assert ev["LOCATION"] == r"Tempe Recreation Reserve\, Field 28"
    assert ev["URL"] == MATCH_URL_BASE + "Omep8Pwj1d"
    assert ev["UID"] == "ld45MgG3xm@dribl"


def test_origin_from_match_url_base():
    assert origin_from(MATCH_URL_BASE) == "https://marrickvillefc.dribl.com"
    assert origin_from("https://esfa.dribl.com/matchcentre?m=") == "https://esfa.dribl.com"
    assert origin_from(None) == "https://cdsfa.dribl.com"


# --- AEST/AEDT changeover ---
# Dribl sends UTC; the .ics stays in UTC and calendar apps localise it, so
# DTSTART must be the API instant unchanged either side of a changeover.
# diff_ics._fmt_dt is the one place we localise (notification text).

def _at(fixture: dict, utc: str) -> dict[str, str]:
    fixture["attributes"]["date"] = utc
    return _event(fixture)


def test_aest_to_aedt_spring_forward(fixture):
    # Sun 4 Oct 2026: clocks go 02:00 AEST -> 03:00 AEDT (15:00 UTC Sat 3 Oct).
    before = _at(fixture, "2026-10-03T15:30:00.000000Z")
    assert before["DTSTART"] == "20261003T153000Z"
    assert _fmt_dt(before["DTSTART"]) == "Sun 4 Oct 1:30am"   # AEST, UTC+10
    after = _at(fixture, "2026-10-03T16:30:00.000000Z")
    assert _fmt_dt(after["DTSTART"]) == "Sun 4 Oct 3:30am"    # AEDT, UTC+11


def test_aedt_to_aest_fall_back(fixture):
    # Sun 5 Apr 2026: clocks go 03:00 AEDT -> 02:00 AEST (16:00 UTC Sat 4 Apr),
    # so 02:30 local happens twice, an hour apart.
    first = _at(fixture, "2026-04-04T15:30:00.000000Z")
    second = _at(fixture, "2026-04-04T16:30:00.000000Z")
    assert _fmt_dt(first["DTSTART"]) == _fmt_dt(second["DTSTART"]) == "Sun 5 Apr 2:30am"


def test_same_local_kickoff_either_side_of_changeover(fixture):
    # A Thursday 7pm game is 09:00 UTC in AEST but 08:00 UTC in AEDT.
    assert _fmt_dt(_at(fixture, "2026-10-01T09:00:00.000000Z")["DTSTART"]) == "Thu 1 Oct 7:00pm"
    assert _fmt_dt(_at(fixture, "2026-10-08T08:00:00.000000Z")["DTSTART"]) == "Thu 8 Oct 7:00pm"
