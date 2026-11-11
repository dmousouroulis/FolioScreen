# Security

## What FolioScreen stores, and where

| Item | macOS | Windows | Protection |
|---|---|---|---|
| SnapTrade and Tiingo keys | Keychain (service `FolioScreen`) | Credential Manager (`FolioScreen`) | Entered at hidden prompts; never in files, arguments, logs or shell history |
| Microsoft sign-in | Keychain token cache | Token cache encrypted with DPAPI | Plus an account record (no tokens) in the state folder |
| State folder, including the last verified dataset (for rollback) | `~/Library/Application Support/FolioScreen/state` | `%LOCALAPPDATA%\FolioScreen\state` | Readable only by you; keep FileVault / BitLocker on |
| Logs | `~/Library/Logs/FolioScreen/sync.log` | `%LOCALAPPDATA%\FolioScreen\logs\sync.log` | Counts and outcomes only: no amounts, holdings or identifiers |
| Portfolio data | Your own Power BI *My workspace* | the same | Private to you unless you share it |

Account IDs, connection IDs, account numbers and account names are replaced by salted hashes before anything
is built, and a sync refuses to publish if a raw identifier remains. FolioScreen requests read-only brokerage
connections and refuses to sync a connection with trading access.

The repository contains code, a fictional demo portfolio and documentation only. A privacy scan runs in CI and,
once enabled, before every commit (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's **private vulnerability reporting** for this repository
(Security → Report a vulnerability), with steps to reproduce. Never include real credentials, account details or
portfolio data in a report; the fictional demo data is enough to reproduce almost anything.
