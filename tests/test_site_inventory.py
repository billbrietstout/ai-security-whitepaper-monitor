#!/usr/bin/env python3
"""Tests for the site-facing inventory projection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import site_inventory  # noqa: E402


def paper(**overrides):
    record = {
        "wp_id": "WP-0001",
        "issue_number": 1,
        "issue_url": "https://github.com/example/papers/issues/1",
        "state": "open",
        "title": "Example paper",
        "source_org": "Example Lab",
        "url": "https://example.org/paper.pdf",
        "date_published": "2026-01-01",
        "category": "Guide",
        "file_type": "PDF",
        "decision": "include",
        "summary": "One sentence.",
        "axioms": ["Models can be wrong."],
        "invariants": ["Access control stays outside the model."],
        "invariables": ["stale"],
        "principles": ["Least privilege."],
        "opencre_topics": ["Access Control"],
    }
    record.update(overrides)
    return record


class SiteInventoryTest(unittest.TestCase):
    def test_drops_closed_and_duplicate_papers(self):
        inventory = {
            "updated": "2026-11-04",
            "source": "github-issues",
            "papers": [
                paper(),
                paper(wp_id="WP-0002", state="closed", decision="delete_candidate"),
                paper(wp_id="WP-0003", state="closed", decision="duplicate"),
            ],
        }
        full, slim = site_inventory.build(inventory)
        self.assertEqual(full["count"], 1)
        self.assertEqual(full["papers"][0]["wp_id"], "WP-0001")
        self.assertEqual(slim["count"], 1)

    def test_copies_invariants_into_invariables(self):
        inventory = {"updated": "2026-11-04", "papers": [paper()]}
        full, slim = site_inventory.build(inventory)
        self.assertEqual(
            full["papers"][0]["invariables"],
            ["Access control stays outside the model."],
        )
        self.assertEqual(
            slim["papers"][0]["invariables"],
            ["Access control stays outside the model."],
        )
        self.assertNotIn("invariants", slim["papers"][0])


if __name__ == "__main__":
    unittest.main()
