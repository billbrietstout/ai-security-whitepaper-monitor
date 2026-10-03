#!/usr/bin/env python3
"""Apply a change plan to the inventory spreadsheet through the Sheets API.

  .venv/bin/python scripts/sheet_sync.py work/<run>/plan.json            # dry run
  .venv/bin/python scripts/sheet_sync.py work/<run>/plan.json --write    # apply

The plan is a JSON array of operations. Rows are found by column values, never by
sheet row number, and every value is written RAW so Sheets does not turn
"March 2026" into a date. Each operation must match exactly one row (or, for
append, no existing row with the same Link), or the whole plan stops before any
write. A plan can be rerun: an append whose Link is already on the same tab, a
delete whose row is already gone, and an update with no differences count as done.

Operations:
  {"op": "update", "tab": T, "match": {col: value, ...}, "set": {col: value, ...}}
  {"op": "replace", "tab": T, "match": {...}, "row": {col: value, ...}}
      Like update, but every header column not in "row" is cleared, except "#".
  {"op": "append", "tab": T, "row": {col: value, ...}}
      MOSAIC rows get the next "#" automatically. Refused if the Link already
      sits on any inventory tab.
  {"op": "delete", "tab": T, "match": {...}}

Credentials: same service account as scripts/extraction.py.
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import gspread
from gspread.utils import rowcol_to_a1

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extraction import SHEET_ID, open_sheet  # noqa: E402

INVENTORY_TABS = ["MOSAIC", "Peer SDOs", "Government", "Coalitions", "Vendor labs"]


def norm_link(url: str) -> str:
    u = urlsplit(url.strip())
    return f"{u.netloc.lower()}{u.path.rstrip('/')}" + (f"?{u.query}" if u.query else "")


class Tab:
    def __init__(self, ws: gspread.Worksheet):
        self.ws = ws
        values = ws.get_all_values()
        self.header = [h.strip() for h in values[0]] if values else []
        while self.header and not self.header[-1]:
            self.header.pop()
        self.rows = values[1:]
        while self.rows and not any(c.strip() for c in self.rows[-1]):
            self.rows.pop()

    def col(self, name: str) -> int:
        if name not in self.header:
            raise SystemExit(f"{self.ws.title}: no column {name!r}; header is {self.header}")
        return self.header.index(name)

    def get(self, row: list[str], name: str) -> str:
        i = self.col(name)
        return row[i].strip() if i < len(row) else ""

    def find(self, match: dict) -> list[int]:
        return [
            i for i, r in enumerate(self.rows)
            if all(self.get(r, k) == str(v).strip() for k, v in match.items())
        ]


def short(s: str, n: int = 70) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    sheet = open_sheet()
    tabs: dict[str, Tab] = {}

    def tab(name: str) -> Tab:
        if name not in tabs:
            tabs[name] = Tab(sheet.worksheet(name))
        return tabs[name]

    links: dict[str, str] = {}
    for name in INVENTORY_TABS:
        t = tab(name)
        for r in t.rows:
            link = t.get(r, "Link")
            if link:
                links.setdefault(norm_link(link), name)

    errors: list[str] = []
    cell_writes: dict[str, list[dict]] = {}
    appends: dict[str, list[list[str]]] = {}
    deletes: dict[str, list[int]] = {}
    next_num: dict[str, int] = {}
    counts = {"update": 0, "replace": 0, "append": 0, "delete": 0, "already done": 0}

    def write(t: Tab, ri: int, name: str, value: str):
        cell_writes.setdefault(t.ws.title, []).append(
            {"range": rowcol_to_a1(ri + 2, t.col(name) + 1), "values": [[value]]}
        )

    for n, op in enumerate(plan, 1):
        kind, t = op["op"], tab(op["tab"])
        label = f"[{n}] {kind} {op['tab']}"
        if kind in ("update", "replace", "delete"):
            hits = t.find(op["match"])
            if kind == "replace" and not hits:
                hits = t.find({k: op["row"][k] for k in op["match"] if k in op["row"]})
            if kind == "delete" and not hits:
                counts["already done"] += 1
                continue
            if len(hits) != 1:
                errors.append(f"{label}: match {op['match']} found {len(hits)} rows, need 1")
                continue
            ri = hits[0]
            row = t.rows[ri]
            if kind == "delete":
                deletes.setdefault(t.ws.title, []).append(ri)
                print(f"{label} row {ri + 2}: delete {short(' | '.join(row[:3]))}")
            else:
                new = dict(op["set"] if kind == "update" else op["row"])
                if kind == "replace":
                    for h in t.header:
                        if h != "#" and h not in new:
                            new[h] = ""
                changed = [(k, v) for k, v in new.items() if t.get(row, k) != v.strip()]
                spill = [j for j in range(len(t.header), len(row)) if row[j].strip()] if kind == "replace" else []
                if not changed and not spill:
                    counts["already done"] += 1
                    continue
                print(f"{label} row {ri + 2} ({short(' | '.join(row[:3]), 60)})")
                for k, v in changed:
                    print(f"    {k}: {short(t.get(row, k), 50)!r} -> {short(v, 60)!r}")
                    write(t, ri, k, v)
                if spill:
                    print(f"    clear {len(spill)} stray cells past column {rowcol_to_a1(1, len(t.header))[:-1]}")
                    for j in spill:
                        cell_writes.setdefault(t.ws.title, []).append(
                            {"range": rowcol_to_a1(ri + 2, j + 1), "values": [[""]]}
                        )
        elif kind == "append":
            new = op["row"]
            key = norm_link(new.get("Link", ""))
            if key and links.get(key) == op["tab"]:
                same = [r for r in t.rows if norm_link(t.get(r, "Link")) == key]
                if any(all(t.get(r, k) == str(v).strip() for k, v in new.items()) for r in same):
                    counts["already done"] += 1
                else:
                    errors.append(f"{label}: Link already on {op['tab']} with different content; use replace: {new['Link']}")
                continue
            if not key and t.find(new):
                counts["already done"] += 1
                continue
            if key and key in links:
                errors.append(f"{label}: Link already on {links[key]}: {new['Link']}")
                continue
            if key:
                links[key] = op["tab"]
            if "#" in t.header:
                if op["tab"] not in next_num:
                    nums = [int(t.get(r, "#")) for r in t.rows if t.get(r, "#").isdigit()]
                    next_num[op["tab"]] = max(nums, default=0) + 1
                new = {"#": str(next_num[op["tab"]]), **new}
                next_num[op["tab"]] += 1
            unknown = [k for k in new if k not in t.header]
            if unknown:
                errors.append(f"{label}: unknown columns {unknown}")
                continue
            appends.setdefault(t.ws.title, []).append([new.get(h, "") for h in t.header])
            print(f"{label}: add {short(' | '.join(str(new.get(h, '')) for h in t.header[:3]))}")
        else:
            errors.append(f"{label}: unknown op")
            continue
        counts[kind] += 1

    print(f"\n{counts}")
    if errors:
        print("\nPlan stopped; nothing written:")
        for e in errors:
            print(f"  FIX {e}")
        sys.exit(1)
    if not args.write:
        print("Dry run. Rerun with --write to apply.")
        return

    for title, data in cell_writes.items():
        tabs[title].ws.batch_update(data, raw=True)
    for title, rows in appends.items():
        t = tabs[title]
        start = len(t.rows) + 2
        need = start + len(rows) - 1 - t.ws.row_count
        if need > 0:
            t.ws.add_rows(need)
        end = rowcol_to_a1(start + len(rows) - 1, len(t.header))
        t.ws.batch_update([{"range": f"A{start}:{end}", "values": rows}], raw=True)
    for title, idxs in deletes.items():
        for ri in sorted(idxs, reverse=True):
            tabs[title].ws.delete_rows(ri + 2)

    bad = 0
    for title in set(cell_writes) | set(appends):
        fresh = sheet.worksheet(title).get_all_values()
        expected = list(cell_writes.get(title, []))
        if title in appends:
            start = len(tabs[title].rows) + 2
            for k, row in enumerate(appends[title]):
                expected += [{"range": rowcol_to_a1(start + k, c + 1), "values": [[v]]} for c, v in enumerate(row)]
        for w in expected:
            r, c = gspread.utils.a1_to_rowcol(w["range"].split("!")[-1])
            shift = sum(1 for ri in deletes.get(title, []) if ri + 2 < r)
            got = fresh[r - 1 - shift][c - 1] if r - 1 - shift < len(fresh) and c - 1 < len(fresh[r - 1 - shift]) else ""
            if got.strip() != str(w["values"][0][0]).strip():
                bad += 1
                print(f"  VERIFY {title}!{w['range']}: wrote {short(str(w['values'][0][0]), 40)!r}, sheet shows {short(got, 40)!r}")
    print(f"Written to https://docs.google.com/spreadsheets/d/{SHEET_ID}. Verify mismatches: {bad}")


if __name__ == "__main__":
    main()
