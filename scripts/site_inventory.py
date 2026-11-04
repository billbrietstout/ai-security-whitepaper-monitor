#!/usr/bin/env python3
"""Build the aisharedresponsibility.com inventory files from this export.

Keep this transform in step with
ai-shared-responsibility/build/sync_whitepapers.py. The site copies included
open papers. Closed delete-candidates and duplicates stay in this repo only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://aisharedresponsibility.com"
MONITOR = "https://github.com/billbrietstout/ai-security-whitepaper-monitor"
DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/billbrietstout/"
    "ai-security-whitepaper-monitor/master/data/whitepapers.json"
)

FULL_PAPER_KEYS = (
    "wp_id",
    "issue_number",
    "issue_url",
    "title",
    "source_org",
    "url",
    "date_published",
    "category",
    "file_type",
    "summary",
    "axioms",
    "invariants",
    "invariables",
    "principles",
    "opencre_topics",
)
SLIM_PAPER_KEYS = (
    "wp_id",
    "title",
    "source_org",
    "url",
    "date_published",
    "axioms",
    "invariables",
    "principles",
)


def included_papers(inventory: dict) -> list[dict]:
    papers = []
    for paper in inventory.get("papers") or []:
        if paper.get("decision") != "include":
            continue
        if paper.get("state") != "open":
            continue
        papers.append(paper)
    papers.sort(key=lambda p: p.get("wp_id") or "")
    return papers


def project(paper: dict, keys: tuple[str, ...]) -> dict:
    invariants = list(paper.get("invariants") or paper.get("invariables") or [])
    out = {}
    for key in keys:
        if key in ("invariants", "invariables"):
            out[key] = list(invariants)
            continue
        value = paper.get(key)
        if key in ("axioms", "principles", "opencre_topics"):
            out[key] = list(value or [])
        elif value is None:
            out[key] = "" if key not in ("issue_number",) else 0
        else:
            out[key] = value
    return out


def extracted(paper: dict) -> bool:
    return bool(
        paper.get("axioms")
        or paper.get("invariants")
        or paper.get("invariables")
        or paper.get("principles")
    )


def build(inventory: dict) -> tuple[dict, dict]:
    papers = included_papers(inventory)
    updated = inventory.get("updated") or ""
    full_papers = [project(p, FULL_PAPER_KEYS) for p in papers]
    slim_papers = [project(p, SLIM_PAPER_KEYS) for p in papers]
    extracted_count = sum(1 for p in papers if extracted(p))
    full = {
        "$schema_version": "1.0",
        "description": (
            "Included AI security whitepapers from the MOSAIC monitor inventory. "
            "Each record is one GitHub issue. Axioms, invariables, and principles "
            "are copied from that issue. This file is an inventory, not a principle "
            "catalog. The accepted catalogs remain security-principles.json and "
            "ai-agentic-principles.json."
        ),
        "updated": updated,
        "generated_from": DEFAULT_SOURCE,
        "monitor": MONITOR,
        "source": "github-issues",
        "count": len(full_papers),
        "extracted_count": extracted_count,
        "papers": full_papers,
    }
    slim = {
        "$schema_version": "1.0",
        "projection": "slim",
        "full_catalog": f"{SITE}/data/whitepapers.json",
        "description": (
            "Slim projection of whitepapers.json: wp_id, title, source, URL, date, "
            "axioms, invariables, and principles. Fetch the full file for issue "
            "links, summaries, and OpenCRE topics."
        ),
        "updated": updated,
        "count": len(slim_papers),
        "extracted_count": extracted_count,
        "papers": slim_papers,
    }
    return full, slim


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def patch_index(index_path: Path, full_count: int, slim_count: int, updated: str) -> None:
    if not index_path.exists():
        return
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["updated"] = updated
    by_file = {entry.get("file"): entry for entry in index.get("files") or []}
    for name, count in (("whitepapers.json", full_count), ("whitepapers.slim.json", slim_count)):
        entry = by_file.get(name)
        if entry is None:
            continue
        entry["record_count"] = count
    index_path.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", default=str(ROOT / "data" / "whitepapers.json"))
    parser.add_argument("--out", required=True, help="Directory that receives the site JSON files")
    args = parser.parse_args()
    inventory = json.loads(Path(args.export).read_text(encoding="utf-8"))
    full, slim = build(inventory)
    out = Path(args.out)
    write_json(out / "whitepapers.json", full)
    write_json(out / "whitepapers.slim.json", slim)
    print(json.dumps({"updated": full["updated"], "count": full["count"], "extracted_count": full["extracted_count"]}))


if __name__ == "__main__":
    main()
