"""
Regenerate every active team's .ics from teams.toml, commit any changes, and
send per-team ntfy notifications.

Usage (CI):     SECRETS='<toJSON(secrets)>' python3 update.py
Usage (local):  python3 update.py --dry-run   # no secrets, commit or notify
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curl_cffi import requests

from diff_ics import summarise
from dribl_to_ics import DEFAULT_DURATION_MIN, build_api_url, build_calendar, fetch_fixtures

ROOT = Path(__file__).resolve().parent
NTFY_URL = "https://ntfy.sh"


def load_teams(path: Path) -> list[dict[str, Any]]:
    with path.open("rb") as f:
        return tomllib.load(f)["team"]


def load_secrets(active: list[dict[str, Any]]) -> dict[str, str]:
    """Fail before any fetching if an active team's ntfy topic is unset; an
    empty topic would otherwise only surface when a notification is due."""
    secrets = json.loads(os.environ.get("SECRETS") or "{}")
    missing = [t["ntfy_secret"] for t in active if not secrets.get(t["ntfy_secret"])]
    if missing:
        for name in missing:
            print(f"::error::Repo secret {name} is not set", file=sys.stderr)
        sys.exit(1)
    return secrets


def _strip_dtstamp(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.startswith("DTSTAMP")]


def generate(team: dict[str, Any]) -> str:
    url = build_api_url(team["tenant"], team["season"], team.get("club"), team.get("competition"), team.get("league"))
    fixtures = fetch_fixtures(url)
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


def notify(topic: str, title: str, body: str) -> None:
    # JSON publishing keeps UTF-8 titles intact (HTTP headers are Latin-1),
    # and raise_for_status() catches the ntfy 4xx that plain curl ignores.
    r = requests.post(NTFY_URL, json={"topic": topic, "title": title, "message": body, "tags": ["soccer"]}, timeout=30)
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

    failed = False
    changed: list[str] = []
    pending: list[tuple[dict[str, Any], str]] = []
    for team in active:
        path = ROOT / team["out"]
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        try:
            new = generate(team)
        except Exception as exc:  # one team's Dribl outage shouldn't block the others
            print(f"::error::{team['name']}: fetch failed: {exc}", file=sys.stderr)
            failed = True
            continue
        if _strip_dtstamp(old) == _strip_dtstamp(new):
            print(f"{team['name']}: unchanged")
            continue
        path.write_text(new, encoding="utf-8")
        changed.append(team["out"])
        if body := summarise(old, new):
            pending.append((team, body))
        else:
            print(f"{team['name']}: changed, but nothing user-visible")

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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
