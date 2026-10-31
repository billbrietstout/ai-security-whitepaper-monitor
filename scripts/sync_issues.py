#!/usr/bin/env python3
"""Read the inventory issues and print what the export would contain.

  python3 scripts/sync_issues.py

GitHub issues are the source of truth. This command does not create issues,
does not edit issues, and does not read or write the retired Google Sheet.
Grok Bot, or a person, files and closes issues. Run
scripts/export_whitepapers.py when you want data/whitepapers.json rewritten.

The report lists papers, delete candidates, duplicates, and issues that
share a URL with another issue. A shared URL keeps a single WP- id.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory  # noqa: E402


def main() -> None:
    repo = inventory.repository_slug()
    issues = inventory.fetch_issues(repo)
    current = inventory.load_inventory()
    registry = list(current["id_registry"]) if current else []
    updated = current.get("updated", "") if current else ""
    document = inventory.build_inventory(issues, registry=registry, updated=updated, repository=repo)
    print(f"Read {len(issues)} issues from {repo}.")
    print(inventory.format_counts(document))
    folded = [
        (paper["wp_id"], paper["issue_number"], paper["duplicate_issue_numbers"], paper["title"])
        for paper in document["papers"]
        if paper["duplicate_issue_numbers"]
    ]
    if folded:
        print("Issues that share a URL:")
        for wp_id, number, duplicates, title in folded:
            joined = ", ".join(f"#{item}" for item in duplicates)
            print(f"  {wp_id} keeps #{number}; {joined} folded ({title})")
    if current is None:
        print("No data/whitepapers.json yet. Run scripts/export_whitepapers.py to write it.")
        return
    fresh_ids = {entry["url"]: entry["wp_id"] for entry in document["id_registry"]}
    saved_ids = {entry["url"]: entry["wp_id"] for entry in current["id_registry"]}
    moved = [url for url, wp_id in saved_ids.items() if fresh_ids.get(url) not in (None, wp_id)]
    if moved:
        print("WP- ids in the saved export would change. Refusing to treat that as a normal sync.")
        for url in moved:
            print(f"  {saved_ids[url]} -> {fresh_ids.get(url)} for {url}")
        raise SystemExit(1)
    added = [url for url in fresh_ids if url not in saved_ids]
    if added:
        print("These URLs are on GitHub and not in the saved export yet:")
        registry_by_url = {entry["url"]: entry["wp_id"] for entry in document["id_registry"]}
        papers_by_id = {paper["wp_id"]: paper for paper in document["papers"]}
        for url in added:
            wp_id = registry_by_url[url]
            paper = papers_by_id.get(wp_id)
            if paper:
                print(f"  {wp_id} issue #{paper['issue_number']} {paper['title']}")
            else:
                print(f"  {wp_id} {url}")
        print("Run scripts/export_whitepapers.py to add them.")
    else:
        print("Saved WP- ids match this read. Run scripts/export_whitepapers.py --check to compare the full file.")


if __name__ == "__main__":
    main()
