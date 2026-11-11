import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from folio import sync
from folio.model_writer import m_datetime, m_number, m_text, render_report, write_pbip
from folio.privacy_scan import scan

ROOT = Path(__file__).resolve().parent.parent


def test_m_literals():
    assert m_text('a "quoted" value') == '"a ""quoted"" value"'
    assert m_text(None) == "null"
    assert m_number(3.0) == "3" and m_number(0.1) == "0.1" and m_number(None) == "null"
    assert m_datetime("2025-03-01 22:00:05+00:00") == "#datetime(2025, 3, 1, 22, 0, 5)"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("scenario", ["clean", "issues"])
def test_generated_pbip_passes_microsoft_schemas_and_m_parser(tmp_path, scenario):
    ds, prices, _ = sync.build_dataset(demo=True, scenario=scenario, today=date(2026, 11, 10))
    write_pbip(tmp_path, sync.render_model(ds, prices, "FolioScreen"), render_report(), ROOT / "assets" / "CY26SU05.json")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_pbip.py"), str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_privacy_scan_finds_planted_secret(tmp_path):
    (tmp_path / "notes.md").write_text("my key is abc123SECRETVALUE", encoding="utf-8")
    (tmp_path / "known_good_FolioScreen-PoC.json").write_text("{}", encoding="utf-8")
    findings = scan(tmp_path, secret_values=["abc123SECRETVALUE"])
    reasons = {f[1] for f in findings}
    assert "contains a credential value from your credential store" in reasons
    assert "FolioScreen state or report file: must not be committed" in reasons


def test_repository_is_clean():
    findings = [f for f in scan(ROOT) if not f[0].startswith(("tools/node/", "tools/schemas/"))]
    assert findings == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_visual_probe_pbip_passes_schemas_parser_and_field_checks(tmp_path):
    from folio import visual_probe
    visual_probe.write_probe_pbip(tmp_path, ROOT / "assets" / "CY26SU05.json")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_pbip.py"), str(tmp_path), "FolioScreen-Probe"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "FolioScreen-Probe.Report" / "definition" / "pages" / "r2Tooltip" / "page.json").exists()


def test_full_report_builds_and_validates(tmp_path):
    """The designed report: schemas, Power Query, TMDL references and DAX references all clean."""
    import subprocess, sys
    from collections import Counter
    from folio.model_writer import MEASURES
    from folio.report_model import report_measures
    names = [n for n, *_ in MEASURES] + [n for n, *_ in report_measures()]
    assert not [n for n, k in Counter(x.lower() for x in names).items() if k > 1]
    out = tmp_path / "pbip"
    r = subprocess.run([sys.executable, "-m", "folio", "build", "--out", str(out)], capture_output=True, text=True,
                       env={**__import__("os").environ, "FOLIO_HOME": str(tmp_path / "home")})
    assert r.returncode == 0, r.stderr
    v = subprocess.run([sys.executable, "tools/validate_pbip.py", str(out), "FolioScreen"], capture_output=True, text=True)
    assert v.returncode == 0, v.stdout
    d = subprocess.run([sys.executable, "tools/check_dax_refs.py", str(out / "FolioScreen.SemanticModel")], capture_output=True, text=True)
    assert d.returncode == 0, d.stdout
    pages = __import__("json").loads((out / "FolioScreen.Report/definition/pages/pages.json").read_text(encoding="utf-8"))["pageOrder"]
    assert pages[:3] == ["overview", "holdings", "performance"] and "securityDetail" in pages and "chartTip" in pages


def test_report_reference_figures_reconcile():
    """The Python reference used by check-report: the gain breakdown and the metrics rail add up to the total gain."""
    from datetime import date
    from folio import report_check, sync
    ds, prices, _ = sync.build_dataset(demo=True, scenario="clean", today=date(2026, 11, 10))
    e = report_check.expected_figures(ds, prices)
    assert abs(e["Gain Breakdown Gap"]) < 0.005
    assert abs(e["Portfolio Value"] - 72921.39) < 0.005 and abs(e["Net Deposits"] - 61750) < 0.005
    realized = sum(v for k, v in e.items() if k.startswith("Gain|") and k not in ("Gain|Interest", "Gain|Fees")) \
        - e["Unrealized Gain"] - (e["Dividends and Interest"] - e["Gain|Interest"])
    rail = e["Unrealized Gain"] + realized + e["Dividends and Interest"] + e["Account Fees"]
    assert abs(rail - e["Total Gain"]) < 0.005
    assert abs(e["Window TWR|1Y"] - 0.0462) < 5e-5 and abs(e["Money Weighted Return"] - 0.1001) < 5e-5


def test_no_measure_inside_calculate_filters():
    """DAX rejects a measure inside a CALCULATE boolean filter ('PLACEHOLDER ... table filter expression');
    such values must be captured in a VAR first. Found in Security Income on the first Service deploy."""
    import re
    from folio.model_writer import MEASURES
    from folio.report_model import REPORT_TABLES, report_measures
    names = {n for n, *_ in MEASURES} | {n for n, *_ in report_measures()}
    safe = ("FILTER", "REMOVEFILTERS", "ALL", "KEEPFILTERS", "VALUES", "TREATAS", "USERELATIONSHIP", "CROSSFILTER")

    def filter_args(expr):
        for mm in re.finditer(r"CALCULATE(?:TABLE)?\s*\(", expr):
            i, depth, args, cur = mm.end(), 1, [], ""
            while i < len(expr) and depth:
                ch = expr[i]
                depth += ch == "("
                depth -= ch == ")"
                if depth == 1 and ch == ",":
                    args.append(cur)
                    cur = ""
                elif depth >= 1:
                    cur += ch
                i += 1
            args.append(cur)
            yield from (a.strip() for a in args[1:])
    exprs = [e for _, e, *_ in list(MEASURES) + report_measures()] + [d for _, d in REPORT_TABLES.values()]
    bad = [a for e in exprs for a in filter_args(e) if not a.startswith(safe)
           and any(r in names for r in re.findall(r"(?<![\w'\]])\[([^\]]+)\]", a))]
    assert not bad, bad


def test_privacy_scan_blocks_every_state_file_and_stray_images(tmp_path):
    from folio.privacy_scan import scan
    names = ["known_good_FolioScreen-PoC.json", "last_success.json", "last_run.json", "last_sync_summary.json",
             "check_report_FolioScreen-PoC.json", "verify_FolioScreen-PoC.json", "probe_2026-11-11.json",
             "safety_test.json", "sandbox_snapshot.txt", "config.json", "microsoft_auth_record.json", "history.jsonl"]
    for n in names:
        (tmp_path / n).write_text("{}", encoding="utf-8")
    (tmp_path / "Screenshot 2026-11-11.png").write_bytes(b"\x89PNG")
    (tmp_path / "docs" / "images").mkdir(parents=True)
    (tmp_path / "docs" / "images" / "overview.png").write_bytes(b"\x89PNG")
    (tmp_path / "verify_dax.py").write_text("x = 1", encoding="utf-8")  # a source file whose name merely starts like a report is fine
    found = {rel for rel, _ in scan(tmp_path)}
    assert set(names) | {"Screenshot 2026-11-11.png"} <= found
    assert "docs/images/overview.png" not in found


def test_privacy_scan_ignores_npm_lockfile_checksums(tmp_path):
    """npm's package-lock.json is full of integrity hashes that look like tokens; it is generated, never committed."""
    from folio.privacy_scan import scan
    (tmp_path / "tools" / "node").mkdir(parents=True)
    (tmp_path / "tools" / "node" / "package-lock.json").write_text(
        '{"integrity": "sha512-' + "A" * 80 + '"}', encoding="utf-8")
    assert scan(tmp_path) == []
