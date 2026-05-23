"""
Diff two .ics files and emit a short human-readable summary of changes.

Used by the GitHub Actions workflow to populate the ntfy notification body.

Usage:
    python3 diff_ics.py --old previous.ics --new current.ics
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Sydney")
MAX_BYTES = 3500  # stay well under ntfy's 4096-byte cap


def parse_ics(text: str) -> dict[str, dict[str, str]]:
    """Return mapping of UID -> {prop: value}. Only cares about a few keys."""
    events: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current is not None and "UID" in current:
                events[current["UID"]] = current
            current = None
        elif current is not None and ":" in line:
            key, _, value = line.partition(":")
            # Strip any parameters from the key (e.g. DTSTART;TZID=...)
            key = key.split(";", 1)[0]
            current[key] = value
    return events


def _ics_unescape(text: str) -> str:
    return (
        text.replace(r"\,", ",")
        .replace(r"\;", ";")
        .replace(r"\n", "\n")
        .replace("\\\\", "\\")
    )


def _is_past(value: str, now: datetime) -> bool:
    """True if an ICS UTC timestamp is before `now`. Unparseable -> treated as
    not past, so we never silently drop a change we couldn't date."""
    try:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return dt < now


def _fmt_dt(value: str) -> str:
    """Convert an ICS UTC timestamp (20260523T050000Z) to a short Sydney string."""
    try:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    local = dt.astimezone(TZ)
    return local.strftime("%a %d %b %I:%M%p").replace(" 0", " ").replace("AM", "am").replace("PM", "pm")


def _summary(ev: dict[str, str]) -> str:
    return _ics_unescape(ev.get("SUMMARY", "(no summary)"))


def _location(ev: dict[str, str]) -> str:
    return _ics_unescape(ev.get("LOCATION", ""))


def _describe(ev: dict[str, str]) -> str:
    parts = [_summary(ev)]
    if "DTSTART" in ev:
        parts.append(_fmt_dt(ev["DTSTART"]))
    loc = _location(ev)
    if loc:
        parts.append(f"@ {loc.split(',')[0]}")  # keep just first part of location
    return " — ".join(parts)


def diff(old: dict[str, dict[str, str]], new: dict[str, dict[str, str]]) -> str:
    old_uids = set(old)
    new_uids = set(new)
    added_uids = new_uids - old_uids
    removed_uids = old_uids - new_uids
    common_uids = old_uids & new_uids

    now = datetime.now(timezone.utc)
    lines: list[str] = []

    # Added: skip if the new fixture is already in the past.
    for uid in sorted(added_uids, key=lambda u: new[u].get("DTSTART", "")):
        if _is_past(new[uid].get("DTSTART", ""), now):
            continue
        lines.append(f"+ {_describe(new[uid])}")

    # Removed: skip if the cancelled fixture was already in the past.
    for uid in sorted(removed_uids, key=lambda u: old[u].get("DTSTART", "")):
        if _is_past(old[uid].get("DTSTART", ""), now):
            continue
        lines.append(f"- {_describe(old[uid])}")

    for uid in sorted(common_uids, key=lambda u: new[u].get("DTSTART", "")):
        old_ev = old[uid]
        new_ev = new[uid]
        # Skip changes to a fixture that is in the past on both old and new
        # dates — an already-played game is not actionable for subscribers.
        if _is_past(old_ev.get("DTSTART", ""), now) and _is_past(new_ev.get("DTSTART", ""), now):
            continue
        changes: list[str] = []
        # Time change
        if old_ev.get("DTSTART") != new_ev.get("DTSTART"):
            changes.append(
                f"time: {_fmt_dt(old_ev.get('DTSTART', ''))} → {_fmt_dt(new_ev.get('DTSTART', ''))}"
            )
        # Location change (just compare full LOCATION string)
        if _location(old_ev) != _location(new_ev):
            old_loc = _location(old_ev).split(",")[0] or "(none)"
            new_loc = _location(new_ev).split(",")[0] or "(none)"
            changes.append(f"ground: {old_loc} → {new_loc}")
        # Summary (team rename — rare)
        if _summary(old_ev) != _summary(new_ev):
            changes.append(f"match: {_summary(old_ev)} → {_summary(new_ev)}")
        if changes:
            lines.append(f"~ {_summary(new_ev)} ({_fmt_dt(new_ev.get('DTSTART', ''))}): " + "; ".join(changes))

    body = "\n".join(lines)
    if len(body.encode("utf-8")) > MAX_BYTES:
        # Truncate at line boundary
        truncated: list[str] = []
        size = 0
        for line in lines:
            line_size = len(line.encode("utf-8")) + 1
            if size + line_size > MAX_BYTES - 60:
                break
            truncated.append(line)
            size += line_size
        truncated.append(f"… (+{len(lines) - len(truncated)} more changes, see calendar)")
        body = "\n".join(truncated)
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    args = parser.parse_args()

    old_text = args.old.read_text(encoding="utf-8") if args.old.exists() and args.old.stat().st_size > 0 else ""
    new_text = args.new.read_text(encoding="utf-8")

    if not old_text:
        n = len(parse_ics(new_text))
        print(f"Initial fixture list ({n} fixtures)")
        return 0

    body = diff(parse_ics(old_text), parse_ics(new_text))
    if not body:
        # Nothing semantically changed (probably just DTSTAMP differences)
        return 0
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
