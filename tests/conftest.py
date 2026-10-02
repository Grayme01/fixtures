import copy
import json
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"

# Coventry City FC, as configured in teams.toml.
TEAM = "WdgpR1DomR"
CALNAME = "Coventry City FC (Marrickville O45 F5s)"
MATCH_URL_BASE = "https://marrickvillefc.dribl.com/matchcentre?m="
STRIP = "Marrickville Over 45 Men "


@pytest.fixture
def fixtures() -> list[dict]:
    """Saved Dribl /api/fixtures page: Coventry's 3 fixtures, one other
    team's fixture and one bye."""
    return json.loads((DATA / "dribl_fixtures.json").read_text(encoding="utf-8"))["data"]


@pytest.fixture
def fixture(fixtures) -> dict:
    """Coventry home v Besiktas, 2026-10-08 09:00 UTC (Thu 8pm AEDT)."""
    return copy.deepcopy(fixtures[0])
