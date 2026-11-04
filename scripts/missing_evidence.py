#!/usr/bin/env python3
"""List included papers that have no evidence level, one batch at a time.

  python3 scripts/missing_evidence.py
  python3 scripts/missing_evidence.py --offset 25

The command reads data/whitepapers.json. It does not call GitHub, and it
does not edit issues. A paper counts as tagged when legacy_notes contains
an Evidence level line the export can read: theoretical, tested,
tested, possibly deployed, or deployed. Delete candidates and duplicates
are skipped. The default batch is 25.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory  # noqa: E402


def format_batch(missing: list[dict], batch: list[dict], *, offset: int, batch_size: int) -> str:
    lines = [
        f"Included papers missing an evidence level: {len(missing)}.",
        f"This batch has {len(batch)}, starting at {offset}.",
    ]
    for paper in batch:
        lines.append(
            f"{paper.get('wp_id')} issue #{paper.get('issue_number')} {paper.get('title')}"
        )
    next_offset = offset + len(batch)
    if next_offset < len(missing):
        lines.append(f"Next batch: python3 scripts/missing_evidence.py --offset {next_offset}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-size", type=int, default=inventory.DEFAULT_EVIDENCE_BATCH)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    document = inventory.load_inventory()
    if document is None:
        raise SystemExit(f"Missing {inventory.JSON_PATH}. Run the export first.")
    missing = inventory.papers_missing_evidence(document)
    batch = inventory.evidence_batch(missing, batch_size=args.batch_size, offset=args.offset)
    print(format_batch(missing, batch, offset=args.offset, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
