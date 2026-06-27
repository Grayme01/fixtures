"""
Resolve a Dribl venue name to a council wet-weather field status.

Reads field_status.json (pushed into this repo by the football-ground-scraper
project) and fuzzily matches a fixture's ground name against the council field
names. Any failure mode — file missing, stale scrape, or no name match — yields
"Unknown", so the weekend summary degrades gracefully and never blocks on field
data.

Used by weekend_summary.py.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Sydney")

# Words that carry no discriminating power in a ground name. Dropped before
# matching so "Balmain Road Sporting Ground" and "Balmain Road (Callan Park)"
# both reduce to the token {balmain ...} and line up.
GENERIC = {
    "park", "oval", "reserve", "field", "fields", "ground", "grounds",
    "sporting", "sports", "sport", "the", "synthetic", "turf", "grass",
    "lower", "upper", "main", "all", "weather", "mini", "roo", "memorial",
    "centre", "center", "complex", "no", "number", "licence", "license",
    "street", "drive", "road", "avenue", "ave", "rd", "st", "recreation",
}


def _norm(text: str) -> str:
    text = text.lower().replace("'", "").replace("’", "")
    text = re.sub(r"[–—\-]", " ", text)   # dashes -> space
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        t for t in _norm(text).split()
        if t not in GENERIC and not t.isdigit() and len(t) > 1
    )


def classify(raw: str) -> str:
    """Map a raw council status string to an emoji-prefixed label."""
    s = raw.strip().lower()
    if not s:
        return "⚪ Unknown"
    if "closed" in s:
        return "🔴 CLOSED"
    if "open" in s and ("only" in s or "sunday" in s or "saturday" in s):
        return f"🟡 {raw.strip()}"   # conditional open, e.g. "open sunday only"
    if s in ("open", "all open") or s.startswith("open"):
        return "🟢 Open"
    return f"⚪ {raw.strip().title()}"


class FieldStatus:
    def __init__(self, path: Path | str):
        self.fields: dict[str, str] = {}
        self.scraped_date: str | None = None
        self.scraped_at: str | None = None
        self.stale = True
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.fields = {k: str(v) for k, v in data.get("fields", {}).items()}
            self.scraped_date = data.get("scraped_date")
            self.scraped_at = data.get("scraped_at")
            today = datetime.now(TZ).strftime("%Y-%m-%d")
            self.stale = self.scraped_date != today
        except (OSError, ValueError, TypeError):
            self.fields = {}

        # Pre-tokenise council names once.
        self._index: list[tuple[frozenset[str], str, str]] = [
            (toks, name, status)
            for name, status in self.fields.items()
            if (toks := _tokens(name))
        ]

    def _matches(self, ground: str) -> list[str]:
        """Council status strings whose field name matches `ground`."""
        norm_ground = _norm(ground)
        # 1. Exact normalised name — most specific, use alone.
        exact = [s for t, n, s in self._index if _norm(n) == norm_ground]
        if exact:
            return exact
        # 2. Token-subset: the ground's significant tokens are all present in
        #    the council name (handles "Balmain Road" -> "Balmain Road (Callan Park)").
        g = _tokens(ground)
        if not g:
            return []
        return [s for t, n, s in self._index if g <= t]

    def status_for(self, ground: str) -> str:
        """Emoji-prefixed status label for a Dribl ground name, or Unknown."""
        if self.stale or not self._index:
            return "⚪ Unknown"
        matches = self._matches(ground)
        if not matches:
            return "⚪ Unknown"
        labels = {classify(s) for s in matches}
        if len(labels) == 1:
            return next(iter(labels))
        # Mixed sub-fields (e.g. turf open, synthetic closed): surface the worst.
        if any(l.startswith("🔴") for l in labels):
            return "🔴 CLOSED (some fields)"
        if any(l.startswith("🟡") for l in labels):
            return "🟡 Partly open"
        return "🟢 Open"

    def note(self) -> str:
        """One-line provenance footer for the summary."""
        if not self.fields:
            return "⚠️ Field status unavailable — showing Unknown."
        if self.stale:
            return f"⚠️ Field data is stale (last scrape {self.scraped_date}) — showing Unknown."
        when = self.scraped_date or "?"
        return f"Field status as at last scrape ({when})."
