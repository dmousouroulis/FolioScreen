# Contributing

Issues and pull requests are welcome.

- **Never include real portfolio data** in an issue, screenshot, test or fixture. Use the demo (`--demo`) or the
  SnapTrade Sandbox, whose data is simulated.
- Enable the privacy check once per clone: `git config core.hooksPath tools/git-hooks`.
- Run the checks before opening a pull request (CI runs the same ones):

```bash
pip install -r requirements-dev.txt
(cd tools/node && npm install)                  # PowerShell: Push-Location tools/node; npm install; Pop-Location
python -m pytest -q
python -m folio build --out pbip && python tools/validate_pbip.py pbip FolioScreen
python tools/check_dax_refs.py pbip/FolioScreen.SemanticModel
python -m folio privacy-scan
```

- A change to a figure needs the matching change in the Python reference (`folio/report_check.py`), so
  `check-report` keeps comparing every figure independently.
- A change to the report should be checked in the Power BI Service on desktop and on a phone; note what you saw
  in the pull request.
- CI runs on macOS, Windows and Linux. Anything platform-specific (scheduling, file locations, credential storage)
  needs a test in `tests/test_cross_platform.py`.

See [the development guide](docs/development.md) for how each part was built and verified.
