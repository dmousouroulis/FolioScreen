"""Offline checks of a generated PBIP folder.

1. Every PBIR JSON file validates against Microsoft's published JSON schema (fetched copies in tools/schemas).
2. Every Power Query expression (M partitions and parameters) parses with Microsoft's Power Query parser.
3. TMDL structure: tab indentation only, every table file declares exactly one partition, every
   column used by the report exists in the model.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMAS = HERE / "schemas"


BASE = "https://developer.microsoft.com/json-schemas/"


def _local(url: str):
    if not url.startswith(BASE):
        return None
    p = SCHEMAS / url[len(BASE):].split("#")[0]
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _registry():
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7

    def retrieve(uri: str):
        doc = _local(uri)
        if doc is None:
            raise LookupError(f"schema not mirrored locally: {uri} (run tools/fetch_schemas.py)")
        return Resource.from_contents(doc, default_specification=DRAFT7)
    return Registry(retrieve=retrieve)


def schema_for(url: str):
    return _local(url)


def _validate(doc, sch):
    import jsonschema
    cls = jsonschema.validators.validator_for(sch)
    errors = sorted(cls(sch, registry=_registry()).iter_errors(doc), key=lambda e: list(e.absolute_path))
    return errors


def check_pbir(report_dir: Path) -> list:
    errs, checked = [], 0
    for f in sorted(report_dir.rglob("*.json")):
        if "StaticResources" in f.parts:
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        sch = schema_for(doc.get("$schema", ""))
        if sch is None:
            errs.append(f"{f}: no local schema for {doc.get('$schema')}")
            continue
        problems = _validate(doc, sch)
        checked += 1
        for e in problems[:3]:
            errs.append(f"{f.relative_to(report_dir)}: {e.message[:200]} at {list(e.absolute_path)}")
    pbir = json.loads((report_dir / "definition.pbir").read_text(encoding="utf-8"))
    sch = schema_for(pbir["$schema"])
    if sch:
        checked += 1
        for e in _validate(pbir, sch)[:3]:
            errs.append(f"definition.pbir: {e.message[:200]}")
    return errs, checked


def m_sources(model_dir: Path) -> dict:
    """Extract M source blocks from TMDL (partitions '= m' and expressions)."""
    out = {}
    for f in sorted((model_dir / "definition").rglob("*.tmdl")):
        lines = f.read_text(encoding="utf-8").split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(r"\tpartition .+ = m$", line):
                j = i + 1
                while not lines[j].startswith("\t\tsource ="):
                    j += 1
                j += 1
                block = []
                while j < len(lines) and (lines[j].startswith("\t\t\t\t") or lines[j] == ""):
                    block.append(lines[j][4:])
                    j += 1
                out[f"{f.stem}"] = "\n".join(block).strip()
                i = j
                continue
            m = re.match(r"expression (\w+) = (.+?) meta \[", line)
            if m:
                out[f"expr_{m.group(1)}"] = m.group(2)
            i += 1
    return out


def check_m(model_dir: Path) -> tuple:
    srcs = m_sources(model_dir)
    with tempfile.TemporaryDirectory() as td:
        files = []
        for name, text in srcs.items():
            p = Path(td) / (name.replace(" ", "_") + ".m")
            p.write_text(text, encoding="utf-8")
            files.append(str(p))
        r = subprocess.run(["node", str(HERE / "node" / "mparse.js"), *files], capture_output=True, text=True,
                           encoding="utf-8", cwd=str(HERE / "node"))
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    if r.returncode and not fails:
        fails = [r.stderr.strip()[:300] or "parser did not run"]
    return fails, len(srcs)


def check_tmdl(model_dir: Path, report_dir: Path) -> list:
    errs = []
    columns, measures, tables = set(), set(), set()
    for f in sorted((model_dir / "definition").rglob("*.tmdl")):
        text = f.read_text(encoding="utf-8")
        for n, line in enumerate(text.split("\n"), 1):
            lead = line[: len(line) - len(line.lstrip())]
            if line.strip() and " " in lead.replace("\t", "")[:1]:
                pass
            if line.strip() and lead and not lead.startswith("\t"):
                errs.append(f"{f.name}:{n} indented with spaces")
        if f.parent.name == "tables":
            tm = re.match(r"table (?:'([^']+)'|(\S+))", text)
            t = tm.group(1) or tm.group(2)
            tables.add(t)
            if len(re.findall(r"^\tpartition ", text, re.M)) != 1:
                errs.append(f"{f.name}: expected exactly one partition")
            for cm in re.finditer(r"^\tcolumn (?:'([^']+)'|(\S+))", text, re.M):
                columns.add((t, cm.group(1) or cm.group(2)))
            for mm in re.finditer(r"^\tmeasure (?:'([^']+)'|(\S+))", text, re.M):
                measures.add(mm.group(1) or mm.group(2))
    model_refs = set(re.findall(r"^ref table (?:'([^']+)'|(\S+))", (model_dir / "definition/model.tmdl").read_text(encoding="utf-8"), re.M))
    model_refs = {a or b for a, b in model_refs}
    if model_refs != tables:
        errs.append(f"model.tmdl refs differ from table files: {sorted(model_refs ^ tables)}")
    for f in report_dir.rglob("visual.json"):
        for m in re.finditer(r'"(Column|Measure)": \{\s*"Expression": \{\s*"SourceRef": \{\s*"Entity": "([^"]+)"\s*\}\s*\},\s*"Property": "([^"]+)"', f.read_text(encoding="utf-8")):
            kind, ent, prop = m.groups()
            if kind == "Column" and (ent, prop) not in columns:
                errs.append(f"{f.parent.name}: unknown column {ent}[{prop}]")
            if kind == "Measure" and prop not in measures:
                errs.append(f"{f.parent.name}: unknown measure [{prop}]")
    return errs


def main(pbip_dir: str, name: str = "FolioScreen") -> int:
    root = Path(pbip_dir)
    model, report = root / f"{name}.SemanticModel", root / f"{name}.Report"
    pbir_errs, n_json = check_pbir(report)
    m_fails, n_m = check_m(model)
    tmdl_errs = check_tmdl(model, report)
    print(f"PBIR schema validation: {n_json} files checked, {len(pbir_errs)} errors")
    print(f"Power Query parser:     {n_m} expressions parsed, {len(m_fails)} failures")
    print(f"TMDL structure/refs:    {len(tmdl_errs)} problems")
    for e in pbir_errs + m_fails + tmdl_errs:
        print("  - " + e)
    return 1 if (pbir_errs or m_fails or tmdl_errs) else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
