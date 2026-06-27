"""
Build the Friday "this weekend" notification: upcoming fixtures for the chosen
teams with each ground's wet-weather field status appended.

Reads each team's .ics and field_status.json, prints a single notification body
to stdout (the workflow pipes it to ntfy). Designed for a Friday-afternoon run,
but the window is simply "now → end of the coming Sunday" so it is safe any day.

Usage:
    python3 weekend_summary.py --status field_status.json \
        --team "Burwood FC 45 05=burwood.ics" \
        --team "Easts FC G09 Blue PISA=easts_pisa.ics"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from diff_ics import _fmt_dt, _ics_unescape, parse_ics
from field_status import FieldStatus

TZ = ZoneInfo("Australia/Sydney")


def _weekend_window(now: datetime) -> tuple[datetime, datetime]:
    """[now, end of the coming Sunday] in Sydney time. On Sunday, just today."""
    days_to_sunday = (6 - now.weekday()) % 7   # Mon=0 .. Sun=6
    sunday = (now + timedelta(days=days_to_sunday)).date()
    return now, datetime.combine(sunday, time(23, 59, 59), tzinfo=TZ)


def _event_start(ev: dict[str, str]) -> datetime | None:
    val = ev.get("DTSTART", "")
    try:
        return datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC"))
    except ValueError:
        return None


def _team_section(name: str, ics_path: Path, fs: FieldStatus,
                  start: datetime, end: datetime) -> list[str]:
    lines = [f"⚽ {name}"]
    try:
        events = parse_ics(ics_path.read_text(encoding="utf-8")).values()
    except OSError:
        lines.append("  (calendar unavailable)")
        return lines

    upcoming = []
    for ev in events:
        dt = _event_start(ev)
        if dt and start <= dt.astimezone(TZ) <= end:
            upcoming.append((dt, ev))
    upcoming.sort(key=lambda x: x[0])

    if not upcoming:
        lines.append("  No fixture this weekend.")
        return lines

    for _, ev in upcoming:
        summary = _ics_unescape(ev.get("SUMMARY", "(match)"))
        location = _ics_unescape(ev.get("LOCATION", ""))
        ground = location.split(",")[0].strip() if location else ""
        status = fs.status_for(ground) if ground else "⚪ Unknown"
        when = _fmt_dt(ev.get("DTSTART", ""))
        lines.append(f"  {when} — {summary}")
        lines.append(f"     📍 {ground or 'TBC'}  ·  {status}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", type=Path, default=Path("field_status.json"))
    parser.add_argument("--team", action="append", default=[],
                        metavar="NAME=ICS_PATH",
                        help="Repeatable. e.g. --team 'Burwood FC 45 05=burwood.ics'")
    args = parser.parse_args()

    if not args.team:
        print("No --team given.", file=sys.stderr)
        return 2

    fs = FieldStatus(args.status)
    now = datetime.now(TZ)
    start, end = _weekend_window(now)

    blocks: list[str] = []
    for spec in args.team:
        name, _, path = spec.partition("=")
        blocks.append("\n".join(_team_section(name.strip(), Path(path), fs, start, end)))

    body = "\n\n".join(blocks) + "\n\n" + fs.note()
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
