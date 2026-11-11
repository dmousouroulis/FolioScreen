"""Static DAX reference check over a built semantic model: every 'Table'[Column] / Table[Column] reference must
exist, and every bare [Name] must be a measure or a column name known somewhere (virtual columns are listed)."""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "definition" / "tables"
tables, measures, exprs = {}, set(), []
for f in root.glob("*.tmdl"):
    text = f.read_text(encoding="utf-8")
    tname = re.match(r"table\s+'?([^'\n]+?)'?\s*$", text.splitlines()[0]).group(1)
    tables[tname] = set(re.findall(r"^\tcolumn\s+'?([^'\n=]+?)'?\s*$", text, re.M))
    for mm in re.finditer(r"^\tmeasure\s+'?([^'=\n]+?)'?\s*=", text, re.M):
        measures.add(mm.group(1).strip())
    for part in re.split(r"\n\t(?=measure |partition )", text):
        if part.startswith("measure ") or (part.startswith("partition ") and "= calculated" in part):
            exprs.append((f.name, part))
bad = []
virtual = set()
for _, e in exprs:
    virtual |= set(re.findall(r'"(@?\w+)"\s*,', e))  # SELECTCOLUMNS/ADDCOLUMNS/ROW names
for fname, e in exprs:
    body = re.sub(r'"[^"\n]*"', '""', e)  # drop string literals
    for t, col in re.findall(r"'([^']+)'\[([^\]]+)\]", body):
        if t not in tables:
            bad.append((fname, f"unknown table '{t}'"))
        elif col not in tables[t] and not (t == "_Measures" and col in measures):
            bad.append((fname, f"unknown column '{t}'[{col}]"))
    for t, col in re.findall(r"(?<!['\w])([A-Za-z_]\w*)\[([^\]]+)\]", body):
        if t in tables and col not in tables[t]:
            bad.append((fname, f"unknown column {t}[{col}]"))
        elif t not in tables and t.upper() not in ("ROW",):
            bad.append((fname, f"unknown table {t}"))
    for name in re.findall(r"(?<![\w'\]])\[([^\]]+)\]", body):
        if name not in measures and name not in virtual and not any(name in cols for cols in tables.values()):
            bad.append((fname, f"unknown [{name}]"))
for b in sorted(set(bad)):
    print("PROBLEM", *b)
print(f"DAX refs: {len(exprs)} expressions, {len(measures)} measures, {len(set(bad))} problems")
sys.exit(1 if bad else 0)
