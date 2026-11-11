"""Mirror Microsoft's PBIR JSON schemas (and everything they reference) into tools/schemas/.
Source: github.com/microsoft/json-schemas (the published copies of developer.microsoft.com/json-schemas)."""
import json, re, sys, urllib.request
from pathlib import Path
from urllib.parse import urljoin

BASE = "https://developer.microsoft.com/json-schemas/"
RAW = "https://raw.githubusercontent.com/microsoft/json-schemas/main/"
OUT = Path(__file__).resolve().parent / "schemas"
ROOTS = ["fabric/item/report/definition/visualContainer/2.10.0/schema.json",
         "fabric/item/report/definition/page/2.1.0/schema.json",
         "fabric/item/report/definition/report/3.3.0/schema.json",
         "fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
         "fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
         "fabric/item/report/definitionProperties/2.0.0/schema.json",
         "fabric/item/report/definition/visualContainerMobileState/2.5.0/schema.json"]

def refs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                yield v
            else:
                yield from refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)

todo, seen = list(ROOTS), set()
while todo:
    rel = todo.pop()
    if rel in seen:
        continue
    seen.add(rel)
    data = urllib.request.urlopen(RAW + rel).read()
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    for r in refs(json.loads(data)):
        target = r.split("#")[0]
        if not target:
            continue
        absu = urljoin(BASE + rel, target)
        if absu.startswith(BASE):
            todo.append(absu[len(BASE):])
print(f"mirrored {len(seen)} schema files")
