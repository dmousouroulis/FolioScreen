# Changelog

## 0.7.1 — first public preview

- **Report:** Overview, Holdings, Performance and Security detail pages, with separately designed iPhone layouts.
  Every figure is checked against an independent Python calculation (`folio check-report`).
- **Data:** SnapTrade Personal (read-only) → reconciliation → your Power BI My workspace; Tiingo daily closes
  refreshed by Power BI. Holdings and cash exactly as reported; history rebuilt from transactions; every
  discrepancy shown in the Data quality panel.
- **Operation:** nightly sync with launchd, verified after each publish and rolled back on failure; catches up after
  sleep and at login; reports Power BI's refresh allowance instead of retrying.
- **Setup:** `folio setup` (guided: demo first, then your own data) and `folio setup --check` (read-only health check),
  including Power BI's morning price refresh, compared across time zones.
- **Windows:** supported alongside macOS: Credential Manager for keys, Task Scheduler for the nightly sync (daily, at
  logon, and catching up missed runs), `%LOCALAPPDATA%` for state and logs, PowerShell instructions throughout. CI runs
  on macOS, Windows and Linux.
- **Privacy:** credentials in the system credential store only; identifiers pseudonymised; privacy scan in CI and as a
  pre-commit hook, covering credentials, account labels, FolioScreen's state files and stray screenshots.

Known limits: Windows is tested in CI but not yet end to end on a Windows PC; tested with the SnapTrade Sandbox,
not with real brokerages; a seven-night unattended run is in progress.
