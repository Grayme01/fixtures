"""
Fetch fixtures from the Dribl public match-centre API and emit an .ics file.

Usage:
    python3 dribl_to_ics.py              # writes burwood_fixtures.ics
    python3 dribl_to_ics.py --inspect    # print raw payload for debugging
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from curl_cffi import requests

API_URL = (
    "https://mc-api.dribl.com/api/fixtures"
    "?date_range=default"
    "&season=k2KpooqNY5"
    "&competition=R1K3BBXLNQ"
    "&league=BdDDYpGwdb"
    "&club=3yvdWENO05"
    "&tenant=JR1K3RNQ9M"
    "&timezone=Australia/Sydney"
)

# The team you actually play for — used to filter fixtures.
# Set to None to include every fixture in the response.
MY_TEAM_HASH_ID: str | None = "am1QPnXjmw"   # Burwood Football Club 45 05

OUTPUT_PATH = Path("burwood_fixtures.ics")
TZ = ZoneInfo("Australia/Sydney")
DEFAULT_DURATION_MIN = 90


def fetch_fixtures(url: str) -> Any:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Origin": "https://cdsfa.dribl.com",
        "Referer": "https://cdsfa.dribl.com/",
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }
    r = requests.get(url, headers=headers, timeout=30, impersonate="chrome")
    if not r.ok:
        print(f"HTTP {r.status_code}", file=sys.stderr)
        print("Body:", r.text[:1000], file=sys.stderr)
        r.raise_for_status()
    return r.json()


def _parse_dt(value: str) -> datetime:
    """API returns UTC ISO timestamps (trailing Z). Return tz-aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_event(fixture: dict) -> str | None:
    """Convert one fixture object (JSON:API) into a VEVENT block."""
    attrs = fixture.get("attributes", {})

    if MY_TEAM_HASH_ID and MY_TEAM_HASH_ID not in (
        attrs.get("home_team_hash_id"), attrs.get("away_team_hash_id")
    ):
        return None

    if attrs.get("bye_flag"):
        return None

    date_raw = attrs.get("date")
    if not date_raw:
        return None

    start = _parse_dt(date_raw)
    end = start + timedelta(minutes=DEFAULT_DURATION_MIN)

    home = attrs.get("home_team_name", "Home")
    away = attrs.get("away_team_name", "Away")
    summary = f"{home} v {away}"

    location_parts = [
        attrs.get("ground_name"),
        attrs.get("field_name"),
        attrs.get("ground_address"),
    ]
    location = ", ".join(p for p in location_parts if p)

    description_lines = []
    if (league := attrs.get("league_name")):
        description_lines.append(f"League: {league}")
    if (rnd := attrs.get("full_round")):
        description_lines.append(f"Round: {rnd}")
    if (comp := attrs.get("competition_name")):
        description_lines.append(f"Competition: {comp}")
    description = "\n".join(description_lines)

    uid_seed = fixture.get("hash_id") or attrs.get("match_hash_id") or f"{date_raw}-{home}-{away}"
    uid = f"{uid_seed}@dribl-cdsfa"

    lat = attrs.get("ground_latitude")
    lon = attrs.get("ground_longitude")

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_fmt_utc(datetime.now(timezone.utc))}",
        f"DTSTART:{_fmt_utc(start)}",
        f"DTEND:{_fmt_utc(end)}",
        f"SUMMARY:{_ics_escape(summary)}",
    ]
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_ics_escape(description)}")
    if lat is not None and lon is not None:
        lines.append(f"GEO:{lat};{lon}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def build_calendar(fixtures: list[dict]) -> tuple[str, int]:
    events = [e for e in (build_event(f) for f in fixtures) if e]
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//graeme//dribl-fixtures//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Burwood FC 45 05",
        "X-WR-TIMEZONE:Australia/Sydney",
    ]
    return "\r\n".join(header + events + ["END:VCALENDAR", ""]), len(events)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--url", default=API_URL)
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    payload = fetch_fixtures(args.url)

    if args.inspect:
        print(json.dumps(payload, indent=2)[:4000])
        return 0

    fixtures = payload.get("data", []) if isinstance(payload, dict) else []
    if not fixtures:
        print("No fixtures in payload.", file=sys.stderr)
        return 1

    ics, n_events = build_calendar(fixtures)
    args.out.write_text(ics, encoding="utf-8")
    print(f"Wrote {n_events} event(s) (from {len(fixtures)} fixtures in response) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
