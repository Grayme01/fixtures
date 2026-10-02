# fixtures

Auto-updating soccer fixture calendars, plus push notifications when anything changes. Built on GitHub Actions + Pages + ntfy.

## What it does

Every day on a schedule (and on demand) a GitHub Actions workflow runs `update.py`, which for each **active** team in `teams.toml`:

1. Hits the [dribl](https://dribl.com) match-centre API for the team's full-season fixture list.
2. Builds an `.ics` (iCalendar) with every fixture, its ground, league/round metadata and a link back to the dribl match page.
3. Compares it with the committed `.ics` (ignoring `DTSTAMP`) and:
    - **Commits** it if anything changed, so GitHub Pages serves a fresh feed.
    - **Pushes an ntfy notification** to the team's topic if something user-visible changed (fixture added, removed, time/ground updated).

The committed `.ics` files are served as static URLs from GitHub Pages. Calendar apps (Google, Apple, Outlook, etc.) subscribe to those URLs and refresh on their own cadence (Google ~12–24h).

## Teams currently tracked

| Team | Association | `.ics` URL | ntfy topic (repo secret) |
|---|---|---|---|
| Coventry City FC (Marrickville F5s, Over 45 Men Black) | Marrickville FC (own tenant, summer five-a-side) | `marrickville_coventry_o45_2026.ics` | `NTFY_TOPIC_MARRICKVILLE` |

Coventry City titles drop the repeated `Marrickville Over 45 Men ` prefix from team names, and events are 45 minutes long.

## Archived teams (2026 winter season)

These have `active = false` in `teams.toml`, so they are never fetched and their `.ics` files stay frozen at the same URLs for existing subscribers. To revive one for a new season, update its `season` (and any other hashes) and set `active = true`.

| Team | Association | `.ics` URL |
|---|---|---|
| Burwood FC 45 05 | CDSFA | `burwood.ics` |
| Burwood FC 45 03 (Over 45s Div 3) | CDSFA | `burwood_45_03.ics` |
| Easts FC G09 Blue PISA | ESFA | `easts_pisa.ics` |

Public URL prefix: `https://grayme01.github.io/fixtures/`.

Easts titles also carry a kit-colour circle: `🔵` when PISA is the home team (listed first), `⚪` when away.

The pre-`teams.toml` workflow (one copied YAML block per team), plus the retired Friday weekend-summary / field-status code, is kept in the `season-2026` tag.

## Schedule

Runs at:

- **Mon–Fri ~10:13 Sydney AEST** (`13 0 * * 1-5` UTC)
- **Sat–Sun ~08:13 Sydney AEST** (`13 22 * * 5,6` UTC, i.e. Fri/Sat 22:13 UTC)

Plus `workflow_dispatch` from the Actions tab on demand.

GitHub Actions cron is in UTC and best-effort. In practice runs have landed 2–5 hours late, so don't rely on the exact time. During AEDT (~Oct–Apr) the runs fire 1h later than the labels.

## Monitoring

All of these go to the `NTFY_TOPIC_HEARTBEAT` topic, which only the maintainer subscribes to.

- **Failure alert:** if any step of a run fails, an `if: failure()` step posts a link to the run log. A fetch or notify failure for one team doesn't stop the other teams, but still fails the run.
- **Weekly heartbeat:** on scheduled Thursday runs, if no auto-commits have landed in the past 7 days, a "still alive" message is sent.
- **Season health warnings:** `update.py` warns when an active team has no future fixtures left, or its season is no longer `is_current` on dribl. These are sent on manual runs and on Thursday scheduled runs (so a finished season nags weekly, not daily), and logged on every run.
- **Keepalive:** GitHub disables scheduled workflows in a public repo after 60 days without activity. `keepalive.yml` runs on the 1st of each month and re-enables the workflows through the API, which resets that clock without a dummy commit.

Not yet done: an outside dead-man's switch (e.g. a healthchecks.io ping on every run). Without it, a workflow that stops being scheduled at all shows up only as a missing Thursday heartbeat.

## Files

| Path | Purpose |
|---|---|
| `teams.toml` | One `[[team]]` block per calendar: dribl hashes, display options, output file, ntfy secret name, `active` flag. |
| `update.py` | Loops over the active teams: generate, diff, commit, notify, health warnings. `--dry-run` writes the `.ics` files and prints would-be notifications without committing or sending. |
| `dribl_to_ics.py` | Dribl client and `.ics` builder (paginated via `meta.next_cursor`; `Origin` taken from the team's match-centre URL). Also a standalone CLI: `--tenant --season --club [--competition --league] --team --calname --match-url-base [--home-prefix --away-prefix --strip-team-prefix --duration] --out`. |
| `diff_ics.py` | Parses old and new `.ics` and builds the ntfy-bound summary of added/removed/changed future fixtures (DTSTART, LOCATION, SUMMARY only). Also a CLI: `--old --new`. |
| `tests/` | pytest suite using a saved dribl response; includes the AEST/AEDT changeovers and a byte-for-byte check against a published `.ics`. |
| `.github/workflows/update-fixtures.yml` | Scheduled workflow: runs `update.py`, the Thursday heartbeat and the failure alert. |
| `.github/workflows/tests.yml` | Runs pytest on every push and pull request. |
| `.github/workflows/keepalive.yml` | Monthly re-enable of the scheduled workflows. |
| `requirements.txt` / `requirements-dev.txt` | Pinned runtime (`curl_cffi`) and test (`pytest`) dependencies. |
| `coventry.html` | Public one-tap subscribe page for Coventry City FC (Apple / Google / Outlook buttons, copy-link fallback). Must never contain an ntfy topic name. |
| `*.ics` | The served calendars; rewritten only when an active team's content changes. |

## Adding another team

1. **Find the team's dribl hashes.** Open the association's match centre (e.g. `cdsfa.dribl.com`, `esfa.dribl.com`, `marrickvillefc.dribl.com`), filter to club + league, and pick a fixture involving the team. In the DevTools network panel find the `mc-api.dribl.com/api/fixtures` request: `tenant`, `season`, `club`, `competition` and `league` are query params, and the fixture's `home_team_hash_id` / `away_team_hash_id` gives the team hash. To get a tenant hash from a subdomain, call `mc-api.dribl.com/api/tenants?slug=<subdomain>`. `app.dribl.com/team?q=` links are member-app links with numeric IDs that the public API won't accept.

2. **Create the ntfy topic.** Generate a random topic name, subscribe to it, and add it as a repo secret named `NTFY_TOPIC_<TEAM>` in **Settings → Secrets and variables → Actions**.

3. **Add a `[[team]]` block to `teams.toml`** with `active = true`, the hashes, `calname`, `match_url_base` (`https://<subdomain>.dribl.com/matchcentre?m=`), `out` and `ntfy_secret`. Check it locally with `python3 update.py --dry-run`.

4. **Pass the secret to the workflow.** Add `NTFY_TOPIC_<TEAM>: ${{ secrets.NTFY_TOPIC_<TEAM> }}` to the `env:` of the `Update active teams` step in `update-fixtures.yml`. Don't replace these lines with `${{ toJSON(secrets) }}`: GitHub flags that as possibly malicious and holds every run for manual approval. If the line is missing, `update.py` fails at startup and names the secret.

5. **Push, then run the workflow manually.** The first run sends `Initial fixture list (N fixtures)`. GitHub Pages needs no per-team setup.

## ntfy notification format

Notification body lists per-fixture changes:

```
+ <home> v <away> — <date/time> — @ <ground>     # new fixture
- <home> v <away> — <date/time> — @ <ground>     # cancelled fixture
~ <home> v <away> (<date>): time: <old> → <new>; ground: <old> → <new>     # changed fixture
```

Times are shown in Sydney local time. Changes to fixtures already in the past are left out. Bodies are capped at ~3.5 KB to stay under ntfy's 4 KB limit; longer diffs are truncated with `… (+N more changes, see calendar)`.

## Local dev

Needs Python 3.12+.

```bash
pip install -r requirements-dev.txt
pytest
python3 update.py --dry-run       # regenerate active teams' .ics; no commit or notify
```

`curl_cffi` is needed because dribl's WAF blocks plain `requests`; `impersonate="chrome"` makes the TLS handshake pass.
