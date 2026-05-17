"""
Fetch fixtures from the Dribl public match-centre API and emit an .ics file.

Usage:
    python3 dribl_to_ics.py \
        --tenant JR1K3RNQ9M \
        --season k2KpooqNY5 \
        --club 3yvdWENO05 \
        --competition R1K3BBXLNQ \
        --league BdDDYpGwdb \
        --team am1QPnXjmw \
        --calname "Burwood FC 45 05" \
        --out burwood.ics

`--competition` and `--league` are optional — the API returns the full club
fixture list without them, and the script filters down to `--team` client-side.

Use `--inspect` to dump the raw response (truncated) instead of writing .ics.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from curl_cffi import requests

API_BASE = "https://mc-api.dribl.com/api/fixtures"
TZ = ZoneInfo("Australia/Sydney")
DEFAULT_DURATION_MIN = 90


def build_api_url(args: argparse.Namespace) -> str:
    params: dict[str, str] = {
        "date_range": "default",
        "season": args.season,
        "tenant": args.tenant,
        "timezone": "Australia/Sydney",
    }
    if args.club:
        params["club"] = args.club
    if args.competition:
        params["competition"] = args.competition
    if args.league:
        params["league"] = args.league
    return f"{API_BASE}?{urlencode(params)}"


def fetch_fixtures(url: str, max_pages: int = 50) -> list[dict]:
    """Fetch all fixtures, following cursor-based pagination.

    Dribl caps per_page at 30. Caller passes the base URL; this function
    appends `cursor` query params and accumulates pages until exhausted.
    """
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
    sep = "&" if "?" in url else "?"
    all_fixtures: list[dict] = []
    cursor: str | None = None
    for page in range(max_pages):
        page_url = url if cursor is None else f"{url}{sep}cursor={cursor}"
        r = requests.get(page_url, headers=headers, timeout=30, impersonate="chrome")
        if not r.ok:
            print(f"HTTP {r.status_code} on page {page}", file=sys.stderr)
            print("Body:", r.text[:1000], file=sys.stderr)
            r.raise_for_status()
        payload = r.json() if isinstance(r.json(), dict) else {}
        all_fixtures.extend(payload.get("data", []))
        cursor = (payload.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
    else:
        print(f"Hit max_pages={max_pages}; some fixtures may be missing.", file=sys.stderr)
    return all_fixtures


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


def build_event(fixture: dict, team_hash: str | None) -> str | None:
    """Convert one fixture object (JSON:API) into a VEVENT block."""
    attrs = fixture.get("attributes", {})

    if team_hash and team_hash not in (
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
    uid = f"{uid_seed}@dribl"

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


def build_calendar(fixtures: list[dict], team_hash: str | None, calname: str) -> tuple[str, int]:
    events = [e for e in (build_event(f, team_hash) for f in fixtures) if e]
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//graeme//dribl-fixtures//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(calname)}",
        "X-WR-TIMEZONE:Australia/Sydney",
    ]
    return "\r\n".join(header + events + ["END:VCALENDAR", ""]), len(events)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True, help="dribl tenant hash_id (e.g. JR1K3RNQ9M for CDSFA)")
    parser.add_argument("--season", required=True, help="season hash_id")
    parser.add_argument("--club", help="club hash_id (optional; narrows API response)")
    parser.add_argument("--competition", help="competition hash_id (optional)")
    parser.add_argument("--league", help="league hash_id (optional)")
    parser.add_argument("--team", help="team hash_id to filter to (optional - omit to include all fixtures in response)")
    parser.add_argument("--calname", required=True, help="X-WR-CALNAME (display name in calendar apps)")
    parser.add_argument("--out", type=Path, required=True, help="output .ics path")
    parser.add_argument("--inspect", action="store_true", help="print raw API payload (truncated) and exit")
    args = parser.parse_args()

    url = build_api_url(args)
    fixtures = fetch_fixtures(url)

    if args.inspect:
        print(json.dumps(fixtures, indent=2)[:4000])
        return 0

    if not fixtures:
        print("No fixtures returned.", file=sys.stderr)
        return 1

    ics, n_events = build_calendar(fixtures, args.team, args.calname)
    args.out.write_text(ics, encoding="utf-8")
    print(f"Wrote {n_events} event(s) (from {len(fixtures)} fixtures in response) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
