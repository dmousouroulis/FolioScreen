# FolioScreen development guide

The sections below document how FolioScreen was built and verified, phase by phase.

> **Privacy.** Run everything with the **demo** or the **SnapTrade Sandbox** first. The reports the commands save are
> sanitized (no identifiers, amounts or holdings). Never paste screenshots of a real portfolio.

## Setup (macOS, once)

The project must **not** live in Desktop, Documents, Downloads or iCloud Drive: macOS blocks background
jobs from reading those folders.

```bash
mkdir -p ~/Developer && cd ~/Developer
unzip ~/Downloads/folioscreen-poc.zip        # creates ~/Developer/folioscreen
cd folioscreen
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Every command below is run from `~/Developer/folioscreen` with `source .venv/bin/activate` done first.
Credentials are typed into hidden prompts and stored in the macOS Keychain; they are never command-line
arguments, so they never reach Terminal history.

## Test sequence

### Part A — Power BI pipeline with the demo (no brokerage, no Tiingo)

| Step | Command / action | Pass when | Paste back |
|---|---|---|---|
| A1 | `python -m folio auth login` (browser opens once), then `python -m folio auth test` | `auth test` prints token lifetimes **without opening a browser** | the `auth test` output |
| A2 | `python -m folio deploy --demo` | creates `FolioScreen-Demo` model + report, initial refresh `Completed`, verification `verified: true` | full output |
| A3 | `python -m folio verify --demo` | `passed: true` (DAX daily values and TWR = Python reference) | the JSON |
| A4 | `python -m folio safety-test` (no schedule needed: Power BI cannot schedule the demo model because all its data is embedded) | data, credential and report-binding checks `true`, `rollback_outcome: ROLLED_BACK` | the checks JSON |
| A5 | Open the `FolioScreen-Demo` report | the page renders; Errors 0; "Portfolio synced …" | screenshot (demo data is fictional) |

A2 is the first time DAX **calculated tables** are deployed this way (Marine Energy Screen never used them).
If A2 fails, paste the error: that is precisely what this test is for.

### Part B — SnapTrade Personal with the Sandbox brokerage

| Step | Command / action | Pass when | Paste back |
|---|---|---|---|
| B1 | Create a free account at dashboard.snaptrade.com, **enable two-factor authentication**, create a **Personal API key**. Then `python -m folio secrets set snaptrade` | "Stored … in the macOS Keychain" | — |
| B2 | `python -m folio connect --sandbox`, open the link, choose **Self-directed**, Connect | the portal reports success | — |
| B3 | `python -m folio probe` | report shows connection `access_type: read`, Personal auth, rate-limit headers seen, refresh/trading endpoints **not** called | the saved `probe_….json` |
| B4 | `python -m folio sync --dry-run` | outcome `DRY_RUN`; nothing sent to Power BI | `reports/last_sync_summary.json` |
| B5 | `python -m folio probe --sandbox-dump` (refuses unless every connection is the simulated Sandbox) | prints every Sandbox position and transaction; identifiers replaced | upload `reports/sandbox_snapshot.txt` and `.json` |

Optional: repeat B2–B4 choosing the Sandbox **No transactions** scenario. Expected: performance
`Unavailable`, holdings still shown — no transactions are invented.

### Part C — Live model with Tiingo prices (Sandbox data)

| Step | Command / action | Pass when | Paste back |
|---|---|---|---|
| C1 | Free key at tiingo.com → `python -m folio secrets set tiingo` | stored | — |
| C2 | `python -m folio deploy` | creates `FolioScreen-PoC` | output |
| C3 | Model **Settings → Data source credentials → api.tiingo.com → Edit**: Authentication **Anonymous**, privacy **Organizational**, tick **Skip test connection**, Sign in | saved | — |
| C4 | `python -m folio sync` | outcome `OK`, verification `true` | output + `last_sync_summary.json` |
| C5 | `python -m folio verify` | `passed: true` (uses one Tiingo request per ticker) | the JSON (counts only) |
| C6 | tiingo.com → Account → Usage | requests ≈ one per ticker per refresh (watch for duplicates) | the numbers |
| C7 | Turn on a daily schedule on `FolioScreen-PoC` (e.g. 18:30 Pacific, after Tiingo's corrections), then `python -m folio sync` | the sync output has no "settings changed" warning and `last_run.json` shows `settings.preserved: true` with `schedule_enabled: true` (every sync checks this) | `python -m folio status` |
| C8 | Next day: check the model's refresh history | the scheduled refresh `Completed`, Market date moved forward | refresh history screenshot |

### Part D — Unattended operation

| Step | Command / action | Pass when |
|---|---|---|
| D1 | `python -m folio schedule install --time 21:30` (macOS shows a "Background Items Added" notice for Python: leave it allowed in System Settings → General → Login Items & Extensions) | `python -m folio schedule status` shows `loaded: true` |
| D2 | **Sleep test**: `python -m folio schedule install --time HH:MM` with a time ~10 minutes ahead, close the lid until after that time, reopen, wait a minute, then `tail -n 20 ~/Library/Logs/FolioScreen/sync.log` | a timestamped `Scheduled run started` line from just after you opened the lid, ending in `Sync outcome: OK` |
| D3 | **Reboot test**: restart the Mac and log in; after a minute run the same `tail` command | a new `Scheduled run started` line, ending in `Already synced successfully since the scheduled time …` (correct: last night's run already covered it) |
| D4 | **Expired sign-in test**: `python -m folio auth logout`, then `python -m folio sync` | outcome `AUTH_REQUIRED`, a macOS notification, Power BI untouched; then `python -m folio auth login` and `python -m folio sync` → `OK` |
| D5 | **Stale display**: `python -m folio schedule uninstall`, wait 2 days, open the report | status reads `STALE: portfolio last synced …`; then reinstall with D1 |
| D6 | Leave the schedule (D1, 21:30) running for 7+ days | `python -m folio status` shows a recent `OK` every day, with no browser sign-in in between |

A scheduled run skips only if a sync already succeeded **since the most recent scheduled time**, so a manual
sync during the day never cancels the nightly run.

Paste back `python -m folio status` after D2, D4 and D6.

### Part E — Optional: a real brokerage

Only after A–D pass. `python -m folio connect` (without `--sandbox`) creates a **read-only** link.
Run `probe` and `sync --dry-run` first and paste only those sanitized reports. If the probe shows
unrecognised transaction types, map them in `config.json` (path printed by `folio status`) under
`type_map`, e.g. `{"JNL": "EXTERNAL_CASH"}`, rather than changing any data.

## Phase 5 — The report on live data (SnapTrade Sandbox)

FolioScreen's reference live data is the **SnapTrade Sandbox**: reproducible for everyone, and deliberately imperfect
(four symbols' transactions contradict their holdings, a position predates the history, a money-market fund, and
crypto that Tiingo cannot price), so the report's caution states are exercised for real. Connecting a real
brokerage is optional (`folio connect`) and works the same way.

```bash
python -m folio sync           # live model: report tables and measures, refreshed and verified (1 refresh)
python -m folio deploy         # publishes the report pages to the live model
python -m folio verify         # daily values and returns compared with the Python engine
python -m folio check-report   # every measure evaluated; values, units and cash compared with SnapTrade and Python
```

On the Sandbox, performance is **Unavailable** by design: the reconciliation will not invent the missing
transactions, so return charts are empty and say why, "since start" figures show "--", and the Data quality
panel lists each issue. Holdings, values, units, cash and allocation are complete.

## Phase 4 — The FolioScreen report (demo data first)

The designed report (Overview, Holdings, Performance, Security detail, phone layouts) replaces the validation
page. Deploy it to the **demo** model first; the live model keeps its current report until the demo passes.

```bash
python -m folio deploy --demo          # model + report "FolioScreen-Demo", then an initial refresh
python -m folio check-report --demo    # every measure evaluated; key figures compared with Python
```

**Refresh allowance.** A model in a free or Pro workspace may refresh 8 times in any rolling 24 hours (scheduled
and API refreshes together). Every `deploy --demo` uses one. For report or measure changes, publish without a
refresh: `python -m folio deploy --demo --no-refresh` (the model keeps serving its current data). If the allowance
is used up, `deploy` says so and still publishes the definitions; the nightly sync rolls back cleanly and retries
the next night.

`check-report` prints `PASSED`, or names each failing measure, empty table or mismatched figure. Please send:

1. The output of both commands.
2. Screenshots (Pages pane collapsed): Overview with **Value**, Overview with **Return**, Holdings, Holdings with
   **Account 1** selected, Performance with **1Y** and with **3M**, the chart tooltip (hover the Overview chart).
3. Security detail: on Holdings, right-click **BRCH.X** → **Drill through** → **Security detail**; screenshot,
   then click **← Back**.
4. Holdings with **Account 1** and **ETFs**: only HRZN.X should be listed.
5. iPhone: Overview, Holdings and Performance, held upright, scrolled top to bottom.

Note: the nightly sync now publishes the report's tables and measures to the live model too. If `check-report`
reports a measure error, run `python -m folio schedule uninstall` until it is fixed; a failed refresh is rolled
back automatically either way.

## Phase 2b — Visual capability probe

Before any design work, this report tests which visual techniques actually render in your Power BI Service
and on your iPhone. It uses the fictional demo data, so screenshots are safe to share.

```bash
python -m folio visual-probe deploy
```

It creates **FolioScreen-Probe** (model + report) in My workspace. If an optional technique breaks deployment,
it is dropped automatically and recorded in `reports/visual_probe.json`, so the other tiles still deploy.

This is **round 2**: targeted retests after round 1 (results in `docs/visual-probe-results.md`).
Each tile is labelled R1…R9 with the result you should see. Please send:

1. The deploy output.
2. A screenshot of each of the three round-2 pages (collapse the Pages pane).
3. R5: hover over the chart and screenshot the tooltip.
4. R4: screenshots with **Value** and with **Return** selected.
5. R8: right-click a row → **Drill through** → **Security detail**, then screenshot.
6. iPhone: the three pages in the Power BI app, held upright (R1 and R3 test phone-only text sizes).

## Commands

```text
python -m folio secrets set snaptrade|tiingo     store credentials (hidden prompt, Keychain)
python -m folio secrets status                   which credentials are present (never values)
python -m folio connect [--sandbox]              read-only SnapTrade Connection Portal link
python -m folio probe                            SnapTrade Personal capability report (read-only)
python -m folio setup [--check]                  guided setup / read-only health check
python -m folio auth login|test|logout           Microsoft sign-in (cached in the Keychain)
python -m folio deploy [--demo] [--no-refresh]   create/update model + report in My workspace
python -m folio sync [--demo] [--dry-run]        manual sync (same as the scheduled run)
python -m folio verify [--demo]
python -m folio check-report [--demo]                  DAX vs Python reference, row by row
python -m folio safety-test                      update/rollback preservation test (demo model)
python -m folio status                           last outcome, sign-in, schedule, credentials
python -m folio schedule install|uninstall|status
python -m folio build --out pbip                 write the demo PBIP files (for inspection)
python -m folio privacy-scan                     run before every commit
python -m folio visual-probe deploy|build        visual capability probe (Phase 2b)
```

Sync exit codes: `0` OK/skipped · `2` fetch failed · `3` Microsoft sign-in required · `4` validation failed ·
`5` refresh failed and the previous model was restored · `6` rollback failed · `7` another sync running ·
`8` blocked by policy (trading connection) · `9` not deployed · `10` Power BI rejected the update (model unchanged) ·
`12` Power BI could not use the api.tiingo.com credential · `13` the refresh failed and no verified version exists yet.
In every non-zero case except 6, the report keeps showing the previous, verified data and marks it stale
after 36 hours. A failed refresh leaves the previous data in place (measured by `folio safety-test`), so a
rollback normally restores the previous definition without refreshing again, costing no extra Tiingo requests.

## What runs where, and what is stored

Windows equivalents: Credential Manager for the keys, a DPAPI-encrypted token cache for the sign-in,
`%LOCALAPPDATA%\FolioScreen\state` and `%LOCALAPPDATA%\FolioScreen\logs\sync.log`, and a Task Scheduler task
(`\FolioScreen\Nightly sync`: daily, at logon, and as soon as possible after a missed run) instead of launchd.

| Item | Where (macOS) |
|---|---|
| SnapTrade, Tiingo keys | macOS Keychain (service `FolioScreen`) |
| Microsoft sign-in | Keychain token cache; account record in `~/Library/Application Support/FolioScreen/state` |
| Last verified dataset (for rollback) | same folder, file mode 0600 (keep FileVault on) |
| Logs | `~/Library/Logs/FolioScreen/sync.log` (counts and outcomes only) |
| Portfolio data in Power BI | embedded in the `FolioScreen-PoC` model in **your** My workspace only |
| Repository | code, demo generator, docs; no credentials, identifiers or account data |

SnapTrade account IDs, connection IDs, account numbers and account names are replaced by salted hashes
before anything is built, and the sync refuses to publish if any raw identifier remains.

## Developer checks (run in CI on every change)

```bash
pip install -r requirements-dev.txt
(cd tools/node && npm install)          # Microsoft's Power Query parser
python -m pytest -q                     # all tests (offline)
python -m folio build --out pbip && python tools/validate_pbip.py pbip
```

`validate_pbip.py` validates every report file against Microsoft's published PBIR JSON schemas
(mirrored in `tools/schemas`), parses every Power Query expression with Microsoft's parser, and checks that
every field the report uses exists in the model. **DAX is not validated offline** (no parser exists outside
Power BI); Part A tests it in the Service.

## Status of the architecture's assumptions

| # | Assumption | Status |
|---|---|---|
| 1 | DAX calculated tables deploy and refresh through the Fabric API in a free My workspace | Verified |
| 2 | Definition updates preserve the refresh schedule, data-source credential and report binding | Verified (`safety-test`, and checked on every sync) |
| 3 | REST refresh, refresh history and executeQueries work on a free licence with the default sign-in client | Verified (`verify`, `check-report`) |
| 4 | The cached Microsoft sign-in renews silently for weeks | Renewing silently across sleep and restarts; seven-night test in progress |
| 5 | launchd runs the job after sleep and at login, and a failed night is recovered at the next login | Verified |
| 6 | Tiingo is called once per ticker per refresh | Verified |
| 7 | Real brokerages follow SnapTrade's documented sign and fee conventions | Not tested by the project (its reference data is the Sandbox); the reconciliation flags anything that does not add up |
| 8 | Calculated-table refresh time stays acceptable at real portfolio sizes | Fine at demo and Sandbox sizes (under a minute) |
| 9 | A free or Pro model may refresh 8 times in a rolling 24 hours | Confirmed: refused refreshes are reported, not retried, and the sync rolls back |
| 10 | Windows: Credential Manager, the DPAPI token cache and Task Scheduler behave like their macOS counterparts | Tested in CI (tests, build, validation, task definition); not yet run end to end on a Windows PC |

## Before every commit

```bash
git config core.hooksPath tools/git-hooks     # once per clone: runs the privacy scan before each commit
chmod +x tools/git-hooks/pre-commit           # macOS/Linux: a file uploaded through the browser loses this bit
```

The hook blocks a commit if the scan finds a credential value from your Keychain, a pseudonymised account label,
an account-number pattern or a private state file in the repository.
