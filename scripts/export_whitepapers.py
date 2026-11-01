#!/usr/bin/env python3
"""Rebuild data/whitepapers.json and data/whitepapers.csv from GitHub issues.

  python3 scripts/export_whitepapers.py
  python3 scripts/export_whitepapers.py --check

The script reads issues only. It does not open the retired Google Sheet.
Set GITHUB_TOKEN or GH_TOKEN in the environment. If neither is set, the
script uses the gh CLI login. The token is not printed.

--check compares a fresh read of the issues with the files on disk and
writes nothing. The ``updated`` date already stored in the JSON is kept
for that comparison, so the check does not fail only because the calendar
date changed.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory  # noqa: E402
import validate_whitepapers  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if the files on disk differ")
    args = parser.parse_args()

    repo = inventory.repository_slug()
    issues = inventory.fetch_issues(repo)
    current = inventory.load_inventory()
    registry = list(current["id_registry"]) if current else []
    updated = date.today().isoformat()
    document = inventory.build_inventory(issues, registry=registry, updated=updated, repository=repo)

    if args.check:
        if current is None:
            raise SystemExit(f"Missing {inventory.JSON_PATH}. Run the export without --check.")
        rebuilt = inventory.build_inventory(
            issues,
            registry=registry,
            updated=current.get("updated", ""),
            repository=current.get("repository", repo),
        )
        problems = validate_whitepapers.compare_documents(rebuilt, current)
        if problems:
            print("\n".join(problems))
            raise SystemExit(1)
        print(f"Export matches the issues. {inventory.format_counts(current)}")
        return

    inventory.write_inventory(document)
    newest = ""
    for issue in issues:
        stamp = str(issue.get("updated_at") or "")
        if stamp > newest:
            newest = stamp
    if newest:
        parsed = datetime.fromisoformat(newest.replace("Z", "+00:00")).astimezone(timezone.utc)
        print(f"Newest issue update: {parsed.date().isoformat()} UTC")
    print(f"Wrote {inventory.JSON_PATH.relative_to(inventory.ROOT)}")
    print(f"Wrote {inventory.CSV_PATH.relative_to(inventory.ROOT)}")
    print(inventory.format_counts(document))


if __name__ == "__main__":
    main()
