#!/usr/bin/env python3
"""Tests for the issue parser, WP- id rules, and the retired sheet commands."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import inventory  # noqa: E402
import validate_whitepapers  # noqa: E402

REPO = "example/papers"


def issue(number: int, body: str, title: str = "Paper", state: str = "open") -> dict:
    return {
        "number": number,
        "title": title,
        "state": state,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "body": body,
    }


BODY = """<!-- sheet-url: https://example.org/paper.pdf -->

**Source:** Example Lab
**Link:** https://example.org/paper.pdf
**Sheet row:** [MOSAIC row 2](https://docs.google.com/spreadsheets/d/example)

### Axioms
- Adoption is uneven.

### Invariables
- The model stores its training data.

### Principles
- Least privilege: the operator grants each agent only the tools the task needs.

### OpenCRE Topics
- Access Control

_Synced from the whitepaper sheet. Edit the sheet, not this issue._

### Carried over from the sheet (Oct 31, 2026)
- **Date published:** Aug 2019
- **Category:** Article
- **File type:** PDF
- **Sheet tab and row:** MOSAIC row 2
"""

HAND_BODY = """**Source:** Precize (GitHub project)
**Link:** https://github.com/precize/Agentic-AI-Top10-Vulnerability
**Sheet row:** Not in the sheet yet. Added by hand on Oct 31, 2026.
**Date published:** Not checked

A community list of top 10 vulnerabilities in agentic AI.
"""

DUP_BODY = """Duplicate of #2, created twice by an interrupted sync run.

<!-- removed-duplicate-marker -->

**Source:** Example Lab
**Link:** https://example.org/paper.pdf
**Sheet row:** [MOSAIC row 2](https://docs.google.com/spreadsheets/d/example)

### Axioms
- Adoption is uneven.
"""


class ParseTests(unittest.TestCase):
    def test_sheet_url_is_kept_when_present(self):
        record = inventory.parse_issue(issue(1, BODY, "Security Engineering"))
        self.assertEqual(record["legacy_sheet_url"], "https://example.org/paper.pdf")
        self.assertEqual(record["date_published"], "Aug 2019")
        self.assertEqual(record["category"], "Article")
        self.assertEqual(record["axioms"], ["Adoption is uneven."])
        self.assertEqual(record["decision"], "include")
        self.assertNotIn("Synced from the whitepaper sheet", " ".join(record["axioms"]))

    def test_sheet_url_is_optional(self):
        record = inventory.parse_issue(issue(172, HAND_BODY, "Agentic AI Top 10"))
        self.assertEqual(record["legacy_sheet_url"], "")
        self.assertEqual(record["date_published"], "Not checked")
        self.assertIn("community list", record["summary"])
        self.assertEqual(record["url_key"], "https://github.com/precize/Agentic-AI-Top10-Vulnerability")

    def test_normalize_url_folds_tracking_and_case(self):
        self.assertEqual(
            inventory.normalize_url("HTTP://Example.org/paper/?utm_source=x"),
            "https://example.org/paper",
        )


class IdTests(unittest.TestCase):
    def test_duplicate_url_keeps_one_id(self):
        document = inventory.build_inventory(
            [
                issue(2, BODY, "Security Engineering"),
                issue(1, DUP_BODY, "Security Engineering", state="closed"),
            ],
            updated="2026-10-31",
            repository=REPO,
        )
        self.assertEqual(len(document["papers"]), 1)
        paper = document["papers"][0]
        self.assertEqual(paper["wp_id"], "WP-0001")
        self.assertEqual(paper["issue_number"], 2)
        self.assertEqual(paper["duplicate_issue_numbers"], [1])
        self.assertEqual(validate_whitepapers.check_ids(document), [])
        self.assertEqual(validate_whitepapers.check_schema(document), [])

    def test_ids_stay_on_the_same_url_and_are_not_reused(self):
        first = inventory.build_inventory(
            [
                issue(1, BODY.replace("https://example.org/paper.pdf", "https://example.org/a"), "A"),
                issue(2, HAND_BODY, "B"),
            ],
            updated="2026-10-31",
            repository=REPO,
        )
        by_url = {entry["url"]: entry["wp_id"] for entry in first["id_registry"]}
        self.assertEqual(by_url["https://example.org/a"], "WP-0001")
        self.assertEqual(
            by_url["https://github.com/precize/Agentic-AI-Top10-Vulnerability"],
            "WP-0002",
        )

        second = inventory.build_inventory(
            [
                issue(1, BODY.replace("https://example.org/paper.pdf", "https://example.org/a"), "A"),
                issue(3, HAND_BODY.replace("https://github.com/precize/Agentic-AI-Top10-Vulnerability", "https://example.org/c"), "C"),
            ],
            registry=first["id_registry"],
            updated="2026-10-31",
            repository=REPO,
        )
        second_ids = {entry["url"]: entry["wp_id"] for entry in second["id_registry"]}
        self.assertEqual(second_ids["https://example.org/a"], "WP-0001")
        self.assertEqual(second_ids["https://github.com/precize/Agentic-AI-Top10-Vulnerability"], "WP-0002")
        self.assertEqual(second_ids["https://example.org/c"], "WP-0003")
        self.assertEqual([paper["wp_id"] for paper in second["papers"]], ["WP-0001", "WP-0003"])
        self.assertEqual(validate_whitepapers.check_history(second, first), [])

    def test_moving_an_id_fails_the_history_check(self):
        previous = {
            "id_registry": [{"wp_id": "WP-0001", "url": "https://example.org/a", "issue_number": 1}]
        }
        current = {
            "id_registry": [{"wp_id": "WP-0001", "url": "https://example.org/b", "issue_number": 1}]
        }
        problems = validate_whitepapers.check_history(current, previous)
        self.assertTrue(any("WP-0001" in problem for problem in problems))

    def test_seeded_duplicate_urls_keep_both_ids(self):
        first_body = BODY
        second_body = BODY.replace("https://example.org/paper.pdf", "https://example.org/other")
        seeded = inventory.build_inventory(
            [issue(1, first_body, "First"), issue(2, second_body, "Second")],
            updated="2026-10-31",
            repository=REPO,
        )
        # Pretend both issues were already published with their own ids, then a third copy arrives.
        registry = [
            {"wp_id": "WP-0031", "url": "https://example.org/paper.pdf", "issue_number": 31},
            {"wp_id": "WP-0032", "url": "https://example.org/paper.pdf", "issue_number": 32},
        ]
        document = inventory.build_inventory(
            [
                issue(31, DUP_BODY.replace("Duplicate of #2", "Duplicate of #32"), "Copy", state="closed"),
                issue(32, BODY, "Canonical"),
                issue(40, BODY, "Third copy"),
            ],
            registry=registry,
            updated="2026-10-31",
            repository=REPO,
        )
        by_issue = {paper["issue_number"]: paper["wp_id"] for paper in document["papers"]}
        self.assertEqual(by_issue[31], "WP-0031")
        self.assertEqual(by_issue[32], "WP-0032")
        self.assertNotIn(40, by_issue)
        canonical = next(paper for paper in document["papers"] if paper["issue_number"] == 32)
        self.assertEqual(canonical["duplicate_issue_numbers"], [40])
        self.assertEqual(validate_whitepapers.check_ids(document), [])
        self.assertTrue(seeded["papers"])

    def test_duplicate_wp_id_in_the_file_fails(self):
        document = inventory.build_inventory(
            [issue(1, BODY, "Security Engineering")],
            updated="2026-10-31",
            repository=REPO,
        )
        document["papers"].append(dict(document["papers"][0]))
        problems = validate_whitepapers.check_ids(document)
        self.assertTrue(any("more than one paper" in problem for problem in problems))


class ExportFileTests(unittest.TestCase):
    def test_committed_export_matches_the_schema_and_id_rules(self):
        document = json.loads(inventory.JSON_PATH.read_text(encoding="utf-8"))
        self.assertEqual(validate_whitepapers.check_schema(document), [])
        self.assertEqual(validate_whitepapers.check_ids(document), [])
        numbers = [paper["issue_number"] for paper in document["papers"]]
        self.assertEqual(len(numbers), len(set(numbers)))
        folded = [number for paper in document["papers"] for number in paper["duplicate_issue_numbers"]]
        self.assertTrue(set(numbers).isdisjoint(folded))


class RetiredSheetTests(unittest.TestCase):
    def test_sheet_commands_exit_without_calling_the_sheet(self):
        for name in ("sheet_sync.py", "extraction.py"):
            path = ROOT / "scripts" / name
            completed = subprocess.run(
                [sys.executable, str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0, name)
            combined = f"{completed.stdout}\n{completed.stderr}".lower()
            self.assertIn("retired", combined)

    def test_python_scripts_do_not_open_the_sheet(self):
        banned = ("gspread", "spreadsheets.google", "open_by_key", "service_account")
        offenders = []
        for path in (ROOT / "scripts").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for term in banned:
                if term in text:
                    offenders.append(f"{path.name}: {term}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
