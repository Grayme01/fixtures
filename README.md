# fixtures

Auto-updating soccer fixture calendars for three teams, plus push notifications when anything changes. Built on GitHub Actions + Pages + ntfy.

## What it does

Every day on a schedule (and on demand) a GitHub Actions workflow:

1. Hits the [dribl](https://dribl.com) match-centre API for each team's full-season fixture list.
2. Writes a per-team `.ics` (iCalendar) file with all events, location, league/round metadata, and a link back to the dribl match page.
3. Diffs each freshly-generated `.ics` against the version on `main` and:
    - **Commits** if any non-DTSTAMP content changed (so GitHub Pages serves a fresh feed).
    - **Pushes an ntfy notification** to the team's topic only if something user-visible changed (fixture added, removed, time/ground updated).

The committed `.ics` files are served as static URLs from GitHub Pages. Calendar apps (Google, Apple, Outlook, etc.) subscribe to those URLs and refresh on their own cadence (Google ~12–24h).

## Teams currently tracked

| Team | Association | `.ics` URL | ntfy topic (repo secret) |
|---|---|---|---|
| Burwood FC 45 05 | CDSFA | `burwood.ics` | `NTFY_TOPIC_BURWOOD` |
| Burwood FC 45 03 (Over 45s Div 3) | CDSFA | `burwood_45_03.ics` | `NTFY_TOPIC_BURWOOD_O45_DIV3` |
| Easts FC G09 Blue PISA | ESFA | `easts_pisa.ics` | `NTFY_TOPIC_EASTS` |

Public URL prefix: `https://grayme01.github.io/fixtures/`.

Easts titles also carry a kit-colour circle: `🔵` when PISA is the home team (listed first), `⚪` when away.

## Schedule

Runs at:

- **Mon–Fri 10:00 Sydney AEST** (`0 0 * * 1-5` UTC)
- **Sat–Sun 08:00 Sydney AEST** (`0 22 * * 5,6` UTC, i.e. Fri/Sat 22:00 UTC)

Plus `workflow_dispatch` from the Actions tab on demand.

GitHub Actions cron is in UTC and best-effort (5–15 min drift is normal). The schedule is tuned to AEST since the soccer season runs through winter; during AEDT (~Oct–Apr) the runs fire 1h later than the labels.

## Files

| Path | Purpose |
|---|---|
| `dribl_to_ics.py` | Fetches fixtures for one team (paginated via `meta.next_cursor`), filters to that team's hash, emits an `.ics`. CLI: `--tenant --season --club [--competition --league] --team --calname --match-url-base [--home-prefix --away-prefix] --out`. |
| `diff_ics.py` | Parses old and new `.ics`, emits a human-readable, ntfy-bound summary of added/removed/changed events (only on semantic fields: DTSTART, LOCATION, SUMMARY). |
| `.github/workflows/update-fixtures.yml` | Cron-triggered workflow that runs all three teams and routes notifications per-team. |
| `burwood.ics`, `burwood_45_03.ics`, `easts_pisa.ics` | The serving `.ics` files; rewritten by the workflow when content changes. |

## Adding another team

1. Find the team in dribl. The fastest way is to open the relevant association's match centre (e.g. `cdsfa.dribl.com` for CDSFA, `esfa.dribl.com` for ESFA), filter to club + league, and pick a fixture involving the team. In DevTools network panel grab the `mc-api.dribl.com/api/fixtures` request — the `tenant`, `season`, `club`, `competition`, `league` hashes are query params. Find the fixture in the JSON response; `home_team_hash_id` / `away_team_hash_id` gives you the team hash.

2. (Optional, for ntfy) generate a random topic name and add it as a new repo secret in **Settings → Secrets and variables → Actions**. Name it `NTFY_TOPIC_<TEAM>`.

3. Add to `.github/workflows/update-fixtures.yml`:
    - A `Snapshot <team>` step that copies the old `.ics` to `/tmp` (use a block scalar to avoid the `HEAD:foo` YAML colon trap).
    - A `Generate <team>` step calling `python3 dribl_to_ics.py` with the team's hashes, a `--calname`, a `--match-url-base` (`https://<subdomain>.dribl.com/matchcentre?m=`), and `--out <team>.ics`.
    - A `Diff <team>` step with `id: diff_<team>` that sets both `changed` (raw content diff, drives commit) and `notify` + `body` (semantic diff, drives ntfy).
    - Add the new `.ics` file to the `git add` line in the commit step.
    - Add a Notify step gated on `steps.diff_<team>.outputs.notify == 'true'`, using `env: BODY:` and `env: TOPIC:`.

4. Push. Trigger the workflow manually to verify. Enable GitHub Pages once already (no per-team setup needed).

## ntfy notification format

Notification body lists per-fixture changes:

```
+ <home> v <away> — <date/time> — @ <ground>     # new fixture
- <home> v <away> — <date/time> — @ <ground>     # cancelled fixture
~ <home> v <away> (<date>): time: <old> → <new>; ground: <old> → <new>     # changed fixture
```

Capped at ~3.5 KB to stay under ntfy's 4 KB body limit; longer diffs are truncated with `… (+N more changes, see calendar)`.

The first time a team's `.ics` is created, the notification reads `Initial fixture list (N fixtures)` rather than listing all events.

## Local dev

Script needs Python 3.12+ and `curl_cffi`. Generate a Burwood `.ics` locally:

```bash
pip install curl_cffi
python3 dribl_to_ics.py \
  --tenant JR1K3RNQ9M --season k2KpooqNY5 \
  --club 3yvdWENO05 --competition R1K3BBXLNQ --league BdDDYpGwdb \
  --team am1QPnXjmw \
  --calname "Burwood FC 45 05" \
  --match-url-base "https://cdsfa.dribl.com/matchcentre?m=" \
  --out burwood.ics
```

`curl_cffi` is needed because dribl's WAF blocks plain `requests`; `impersonate="chrome"` makes the TLS handshake pass.
