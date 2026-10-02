"""
Regenerate every active team's .ics from teams.toml, commit any changes, and
send per-team ntfy notifications. Also warns on the heartbeat topic when an
active team looks finished (no future fixtures, or its season is no longer
current), as a prompt to archive it or roll it to the new season.

Usage (CI):     NTFY_TOPIC_HEARTBEAT=<topic> NTFY_TOPIC_<TEAM>=<topic> ... python3 update.py
Usage (local):  python3 update.py --dry-run   # no secrets, commit or notify
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curl_cffi import requests

from diff_ics import parse_ics, summarise
from dribl_to_ics import DEFAULT_DURATION_MIN, build_api_url, build_calendar, fetch_fixtures, fetch_season, origin_from

ROOT = Path(__file__).resolve().parent
NTFY_URL = "https://ntfy.sh"
HEARTBEAT_SECRET = "NTFY_TOPIC_HEARTBEAT"


def load_teams(path: Path) -> list[dict[str, Any]]:
    with path.open("rb") as f:
        return tomllib.load(f)["team"]


def load_secrets(active: list[dict[str, Any]]) -> dict[str, str]:
    """Fail before any fetching if an active team's ntfy topic is unset; an
    empty topic would otherwise only surface when a notification is due."""
    names = [HEARTBEAT_SECRET] + [t["ntfy_secret"] for t in active]
    secrets = {name: os.environ.get(name, "") for name in names}
    missing = [name for name, value in secrets.items() if not value]
    if missing:
        for name in missing:
            print(f"::error::{name} is empty: create the repo secret and pass it in "
                  "the 'Update active teams' step env", file=sys.stderr)
        sys.exit(1)
    return secrets


def _strip_dtstamp(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith("DTSTAMP")]


def generate(team: dict[str, Any]) -> str:
    url = build_api_url(team["tenant"], team["season"], team.get("club"), team.get("competition"), team.get("league"))
    fixtures = fetch_fixtures(url, origin=origin_from(team.get("match_url_base")))
    if not fixtures:
        raise RuntimeError(f"{team['name']}: no fixtures returned")
    ics, n_events = build_calendar(
        fixtures,
        team.get("team"),
        team["calname"],
        team.get("match_url_base"),
        team.get("home_prefix", ""),
        team.get("away_prefix", ""),
        team.get("strip_team_prefix", ""),
        team.get("duration", DEFAULT_DURATION_MIN),
    )
    print(f"{team['name']}: {n_events} event(s) from {len(fixtures)} fixtures")
    return ics


def health_warnings(team: dict[str, Any], ics: str, now: datetime) -> list[str]:
    warnings = []
    starts = [ev.get("DTSTART", "") for ev in parse_ics(ics).values()]
    # ICS UTC stamps (20261008T090000Z) sort chronologically as strings.
    if not any(s > f"{now:%Y%m%dT%H%M%SZ}" for s in starts):
        warnings.append(f"{team['name']}: no future fixtures left")
    try:
        if not fetch_season(team["tenant"], team["season"], origin_from(team.get("match_url_base")))["is_current"]:
            warnings.append(f"{team['name']}: season {team['season']} is no longer the current Dribl season")
    except Exception as exc:  # a health check shouldn't fail the run
        print(f"::warning::{team['name']}: season check failed: {exc}", file=sys.stderr)
    return warnings


def alert_due(now: datetime) -> bool:
    """Send health warnings on manual runs and on Thursday (UTC) scheduled
    runs, matching the heartbeat, so a finished season nags weekly, not daily."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    return event == "workflow_dispatch" or (event == "schedule" and now.isoweekday() == 4)


def notify(topic: str, title: str, body: str, tags: list[str] | None = None) -> None:
    # JSON publishing keeps UTF-8 titles intact (HTTP headers are Latin-1),
    # and raise_for_status() catches the ntfy 4xx that plain curl ignores.
    r = requests.post(NTFY_URL, json={"topic": topic, "title": title, "message": body, "tags": tags or ["soccer"]}, timeout=30)
    r.raise_for_status()


def commit_and_push(paths: list[str]) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=ROOT, check=True)

    # Author must stay "github-actions": the Thursday heartbeat counts its commits.
    git("-c", "user.name=github-actions", "-c", "user.email=github-actions@users.noreply.github.com",
        "commit", "-m", f"Update fixtures {datetime.now(timezone.utc):%Y-%m-%d}", "--", *paths)
    git("push")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=ROOT / "teams.toml")
    parser.add_argument("--dry-run", action="store_true", help="write .ics files and print bodies; no commit or notify")
    args = parser.parse_args()

    active = [t for t in load_teams(args.config) if t["active"]]
    secrets = {} if args.dry_run else load_secrets(active)

    now = datetime.now(timezone.utc)
    failed = False
    changed: list[str] = []
    pending: list[tuple[dict[str, Any], str]] = []
    warnings: list[str] = []
    for team in active:
        path = ROOT / team["out"]
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        try:
            new = generate(team)
        except Exception as exc:  # one team's Dribl outage shouldn't block the others
            print(f"::error::{team['name']}: fetch failed: {exc}", file=sys.stderr)
            failed = True
            continue
        warnings += health_warnings(team, new, now)
        if _strip_dtstamp(old) == _strip_dtstamp(new):
            print(f"{team['name']}: unchanged")
            continue
        path.write_text(new, encoding="utf-8")
        changed.append(team["out"])
        if body := summarise(old, new):
            pending.append((team, body))
        else:
            print(f"{team['name']}: changed, but nothing user-visible")

    for w in warnings:
        print(f"::warning::{w}", file=sys.stderr)

    if args.dry_run:
        for team, body in pending:
            print(f"--- would notify {team['ntfy_secret']} ---\n{body}")
        return 1 if failed else 0

    if changed:
        subprocess.run(["git", "add", "--", *changed], cwd=ROOT, check=True)
        commit_and_push(changed)

    # Commit first so subscribers are only told about calendars Pages can serve.
    for team, body in pending:
        try:
            notify(secrets[team["ntfy_secret"]], f"{team['name']} fixtures updated", body)
            print(f"{team['name']}: notified")
        except Exception as exc:  # keep notifying the other teams
            print(f"::error::{team['name']}: ntfy failed: {exc}", file=sys.stderr)
            failed = True

    if warnings and alert_due(now):
        notify(secrets[HEARTBEAT_SECRET], "Fixtures: check team config",
               "\n".join(warnings) + "\nArchive the team (active = false) or update its season in teams.toml.",
               tags=["warning"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
