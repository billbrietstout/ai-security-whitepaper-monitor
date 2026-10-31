#!/usr/bin/env python3
"""Turn old extraction results into local paste files.

The Google Sheet was retired on 2026-10-31. This script does not call the
sheet. The live inventory is GitHub issues. See README.md.

Turn refresh-run extraction results into Google Sheets paste files.

  python3 scripts/results-to-paste.py work/refresh-2026-10-03 --date 2026-10-03 --mosaic-start 107

Reads every results-*.json in the folder (format: work/refresh-*/EXTRACTION-BRIEF.md),
keeps include=true items, and writes one TSV per tab and action under data/:
refresh-<date>-<tab>-<action>.tsv. MOSAIC rows get a leading # starting at
--mosaic-start; other tabs have no # column. Bullet refs go to
data/extraction-evidence-<date>.json.
"""

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

_spec = importlib.util.spec_from_file_location("build_paste_files", ROOT / "scripts" / "build-paste-files.py")
_bpf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bpf)

TAB_ORDER = ["MOSAIC", "Peer SDOs", "Coalitions", "Government", "Vendor labs"]


def bullets(items: list) -> str:
    return " · ".join(f"- {(b['text'] if isinstance(b, dict) else b).strip()}" for b in items)


def to_row(r: dict) -> list[str]:
    return [
        r["issuer"],
        r["publication"],
        r["date_published"],
        r["category"],
        r["file_type"],
        r["link"],
        bullets(r["axioms"]),
        bullets(r["invariables"]),
        bullets(r["principles"]),
        bullets(r["opencre_topics"]),
        r.get("blog", ""),
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--mosaic-start", type=int, required=True)
    args = ap.parse_args()

    results = []
    for f in sorted(args.folder.glob("results-*.json")):
        results.extend(json.loads(f.read_text(encoding="utf-8")))
    kept = [r for r in results if r.get("include") is True]
    skipped = [r for r in results if r.get("include") is not True]

    groups: dict[tuple[str, str], list[dict]] = {}
    for r in sorted(kept, key=lambda r: TAB_ORDER.index(r["tab"])):
        groups.setdefault((r["tab"], r.get("action", "add")), []).append(r)

    n = args.mosaic_start
    for (tab, action), items in groups.items():
        rows = []
        for r in items:
            row = to_row(r)
            if tab == "MOSAIC":
                row = [str(n)] + row
                n += 1
            rows.append(row)
        slug = tab.lower().replace(" ", "-")
        path = DATA / f"refresh-{args.date}-{slug}-{action}.tsv"
        _bpf.write_paste_tsv(path, rows)
        print(f"{path.name}: {len(rows)} row(s)")

    evidence = [
        {k: r[k] for k in ("tab", "issuer", "publication", "link", "axioms", "invariables", "principles", "opencre_topics")}
        for r in kept
    ]
    (DATA / f"extraction-evidence-{args.date}.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for r in skipped:
        print(f"skipped: {r['issuer']}: {r['publication']}: {r.get('fetch_error') or r['include_reason'][:80]}")


if __name__ == "__main__":
    main()
