#!/usr/bin/env python3
"""Check data/whitepapers.json against the schema, the WP- id rules, and GitHub.

  python3 scripts/validate_whitepapers.py

The check fails when:

- the file does not match schemas/whitepapers.schema.json
- a WP- id is repeated, malformed, or tied to two URLs
- an id in an earlier export on the base branch has moved to another URL
- a record points at an issue number that does not exist
- the file does not match a fresh read of the issues

Set GITHUB_TOKEN or GH_TOKEN. The token is not printed.
Set VALIDATION_BASE_REF to the branch that holds the last accepted export
(default: master). If that branch has no data/whitepapers.json yet, the
history check is skipped and this file becomes the first id registry.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory  # noqa: E402

ROOT = inventory.ROOT
SCHEMA_PATH = ROOT / "schemas" / "whitepapers.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def check_schema(document: dict) -> list[str]:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(load_schema())
    problems = []
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = "/".join(str(part) for part in error.path) or "(file)"
        problems.append(f"schema: {location}: {error.message}")
    return problems


def check_ids(document: dict) -> list[str]:
    problems = []
    seen_ids: dict[str, tuple[str, int]] = {}
    seen_issues: dict[int, str] = {}
    registry = document.get("id_registry")
    papers = document.get("papers")
    if not isinstance(registry, list) or not isinstance(papers, list):
        return ["id check: papers and id_registry must be arrays"]

    for entry in registry:
        if not isinstance(entry, dict):
            problems.append("id check: a registry entry is not an object")
            continue
        wp_id = entry.get("wp_id")
        url_key = entry.get("url")
        issue_number = entry.get("issue_number")
        if not isinstance(wp_id, str) or not inventory.WP_ID_RE.fullmatch(wp_id):
            problems.append(f"id check: registry id {wp_id!r} is not WP- and four digits")
            continue
        if not isinstance(issue_number, int):
            problems.append(f"id check: {wp_id} is missing issue_number")
            continue
        if not isinstance(url_key, str) or not url_key:
            problems.append(f"id check: {wp_id} has an empty URL")
            continue
        normalized = inventory.normalize_url(url_key)
        if normalized != url_key:
            problems.append(f"id check: registry URL for {wp_id} is not normalized")
        if wp_id in seen_ids and seen_ids[wp_id] != (normalized, issue_number):
            problems.append(f"id check: {wp_id} is tied to two issues")
        if issue_number in seen_issues and seen_issues[issue_number] != wp_id:
            problems.append(f"id check: issue {issue_number} has both {seen_issues[issue_number]} and {wp_id}")
        seen_ids[wp_id] = (normalized, issue_number)
        seen_issues[issue_number] = wp_id

    paper_ids: set[str] = set()
    paper_issues: set[int] = set()
    for paper in papers:
        if not isinstance(paper, dict):
            problems.append("id check: a paper is not an object")
            continue
        wp_id = paper.get("wp_id")
        url = paper.get("url")
        issue_number = paper.get("issue_number")
        if not isinstance(wp_id, str) or not isinstance(url, str) or not isinstance(issue_number, int):
            problems.append("id check: a paper is missing wp_id, url, or issue_number")
            continue
        if wp_id in paper_ids:
            problems.append(f"id check: {wp_id} is used by more than one paper")
        paper_ids.add(wp_id)
        if issue_number in paper_issues:
            problems.append(f"id check: issue {issue_number} is used by more than one paper")
        paper_issues.add(issue_number)
        url_key = inventory.normalize_url(url)
        if seen_ids.get(wp_id) != (url_key, issue_number):
            problems.append(
                f"id check: {wp_id} does not match the registry for issue {issue_number}"
            )
        for duplicate in paper.get("duplicate_issue_numbers", []):
            if duplicate in paper_issues or duplicate in seen_issues:
                problems.append(f"id check: folded issue {duplicate} also has its own WP- id")
    return problems


def check_history(current: dict, previous: dict | None) -> list[str]:
    """Ids already published on the base branch must stay on the same URL."""
    if previous is None:
        return []
    problems = []
    current_by_id = {
        entry["wp_id"]: entry
        for entry in current.get("id_registry", [])
        if isinstance(entry, dict) and "wp_id" in entry
    }
    for entry in previous.get("id_registry", []):
        if not isinstance(entry, dict):
            continue
        wp_id = entry.get("wp_id")
        url = entry.get("url")
        issue_number = entry.get("issue_number")
        if not isinstance(wp_id, str) or not isinstance(url, str):
            continue
        if wp_id not in current_by_id:
            problems.append(f"stable id: {wp_id} was removed from the registry")
            continue
        current_entry = current_by_id[wp_id]
        if current_entry.get("url") != url:
            problems.append(f"stable id: {wp_id} moved from {url} to {current_entry.get('url')}")
        if issue_number is not None and current_entry.get("issue_number") != issue_number:
            problems.append(
                f"stable id: {wp_id} moved from issue {issue_number} to issue {current_entry.get('issue_number')}"
            )
    return problems


def load_base_document(ref: str) -> dict | None:
    try:
        raw = subprocess.check_output(
            ["git", "show", f"origin/{ref}:data/whitepapers.json"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None
    try:
        return json.loads(raw.decode())
    except json.JSONDecodeError:
        raise SystemExit(f"origin/{ref}:data/whitepapers.json is not valid JSON.") from None


def issue_numbers(document: dict) -> set[int]:
    numbers: set[int] = set()
    for paper in document.get("papers", []):
        numbers.add(int(paper["issue_number"]))
        for duplicate in paper.get("duplicate_issue_numbers", []):
            numbers.add(int(duplicate))
    return numbers


def compare_documents(rebuilt: dict, committed: dict) -> list[str]:
    problems = []
    rebuilt_papers = {paper["wp_id"]: paper for paper in rebuilt["papers"]}
    committed_papers = {paper["wp_id"]: paper for paper in committed["papers"]}
    missing = sorted(set(rebuilt_papers) - set(committed_papers))
    extra = sorted(set(committed_papers) - set(rebuilt_papers))
    for wp_id in missing:
        paper = rebuilt_papers[wp_id]
        problems.append(f"export is missing {wp_id} for issue #{paper['issue_number']}")
    for wp_id in extra:
        paper = committed_papers[wp_id]
        problems.append(f"export has {wp_id} for issue #{paper['issue_number']} and the issues do not")
    for wp_id in sorted(set(rebuilt_papers) & set(committed_papers)):
        if rebuilt_papers[wp_id] != committed_papers[wp_id]:
            changed = [
                key for key in rebuilt_papers[wp_id]
                if rebuilt_papers[wp_id].get(key) != committed_papers[wp_id].get(key)
            ]
            shown = ", ".join(changed[:8])
            problems.append(f"export {wp_id} differs from issue #{committed_papers[wp_id]['issue_number']}: {shown}")
    rebuilt_registry = [(entry["wp_id"], entry["url"]) for entry in rebuilt["id_registry"]]
    committed_registry = [(entry["wp_id"], entry["url"]) for entry in committed["id_registry"]]
    if rebuilt_registry != committed_registry:
        problems.append("id registry does not match the issues plus the ids already reserved in this file")
    for key in ("version", "source", "repository", "sheet"):
        if rebuilt.get(key) != committed.get(key):
            problems.append(f"{key} in the file does not match this export")
    return problems


def check_issue_links(document: dict, issues: list[dict], repository: str) -> list[str]:
    live = {int(issue["number"]): issue for issue in issues if "pull_request" not in issue}
    problems = []
    for paper in document["papers"]:
        number = int(paper["issue_number"])
        issue = live.get(number)
        if issue is None:
            problems.append(f"{paper['wp_id']} links to issue #{number}, and that issue does not exist")
            continue
        expected_url = f"https://github.com/{repository}/issues/{number}"
        if paper.get("issue_url") != expected_url or issue.get("html_url") != expected_url:
            problems.append(f"{paper['wp_id']} issue URL does not match issue #{number}")
        for duplicate in paper.get("duplicate_issue_numbers", []):
            if int(duplicate) not in live:
                problems.append(
                    f"{paper['wp_id']} lists duplicate issue #{duplicate}, and that issue does not exist"
                )
    live_numbers = set(live)
    exported = issue_numbers(document)
    for number in sorted(live_numbers - exported):
        title = str(live[number].get("title") or "")
        problems.append(f"issue #{number} is not in the export ({title})")
    for number in sorted(exported - live_numbers):
        problems.append(f"the export lists issue #{number}, and that issue does not exist")
    return problems


def main() -> None:
    if not inventory.JSON_PATH.exists():
        raise SystemExit(f"Missing {inventory.JSON_PATH}.")
    document = json.loads(inventory.JSON_PATH.read_text(encoding="utf-8"))
    problems = check_schema(document) + check_ids(document)
    if problems:
        print("\n".join(problems))
        raise SystemExit(1)

    ref = os.environ.get("VALIDATION_BASE_REF", "master").strip() or "master"
    if not re_fullmatch_ref(ref):
        raise SystemExit("VALIDATION_BASE_REF must be a branch name.")
    previous = load_base_document(ref)
    if previous is None:
        print(f"No data/whitepapers.json on origin/{ref} yet. This file is the first WP- id registry.")
    else:
        problems.extend(check_history(document, previous))
    if problems:
        print("\n".join(problems))
        raise SystemExit(1)

    repository = document["repository"]
    issues = inventory.fetch_issues(repository)
    problems.extend(check_issue_links(document, issues, repository))
    rebuilt = inventory.build_inventory(
        issues,
        registry=list(document["id_registry"]),
        updated=document.get("updated", ""),
        repository=repository,
    )
    problems.extend(compare_documents(rebuilt, document))
    if problems:
        print("\n".join(problems))
        raise SystemExit(1)
    print(f"validate-whitepapers: ok ({len(document['papers'])} papers, {len(issues)} issues)")


def re_fullmatch_ref(ref: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9._/-]+", ref)) and ".." not in ref and not ref.startswith("-")


if __name__ == "__main__":
    main()
