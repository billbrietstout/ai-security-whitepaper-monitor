#!/usr/bin/env python3
"""Idempotent filing, resume, and the pull-request guard."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
import urllib.error
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import filing  # noqa: E402
import inventory  # noqa: E402
import open_inventory_pr  # noqa: E402


def pending(wp_id: str, url: str, title: str = "Paper") -> dict:
    raw = filing.normalize_queue_item(
        {
            "title": title,
            "source": "Example Lab",
            "url": url,
            "summary": "A public guidance paper.",
            "date_published": "March 2026",
        },
        1,
    )
    return filing.new_item(raw, wp_id, status="pending", issue_number=None)


def make_store(directory: Path, items: list[dict] | None = None, date: str = "2026-11-04") -> filing.RunStore:
    path = directory / "runs" / f"{date}.json"
    store = filing.RunStore.create(
        path,
        date=date,
        repository="example/papers",
        project_owner="example",
        project_number=2,
        batch_size=25,
    )
    if items is not None:
        store.data["items"] = items
        store.save()
    return store


class FakeResponse:
    def __init__(self, payload: dict, status: int = 201):
        self.raw = json.dumps(payload).encode()
        self.status = status
        self.headers = {}

    def read(self) -> bytes:
        return self.raw

    def close(self) -> None:
        return None


class FakeGitHub:
    def __init__(self):
        self.issues: list[dict] = []
        self.calls: list[object] = []
        self.fail_list_remaining = 0
        self.fail_create_remaining = 0
        self.persist_create_on_failure = False
        self.lists_to_fail_after_create = 0
        self.fail_project_lookup_remaining = 0
        self.fail_project_add_remaining = 0
        self.persist_add_on_failure = False
        self.block_add = False
        self.project_items: dict[tuple[str, str], str] = {}
        self.next_number = 1
        self.snapshot_path: Path | None = None
        self.snapshots: list[str] = []

    def list_issues(self) -> list[dict]:
        self.calls.append("list")
        if self.fail_list_remaining:
            self.fail_list_remaining -= 1
            raise filing.GithubError(503, "503 ghp_supersecretvalue")
        if self.lists_to_fail_after_create and self.calls.count("create"):
            self.lists_to_fail_after_create -= 1
            raise filing.GithubError(503, "503 ghp_supersecretvalue")
        return [dict(issue) for issue in self.issues]

    def get_issue(self, number: int) -> dict:
        self.calls.append(("get", number))
        for issue in self.issues:
            if issue["number"] == number:
                return dict(issue)
        raise filing.GithubError(404, "missing")

    def create_issue(self, title: str, body: str) -> dict:
        self.calls.append("create")
        if self.fail_create_remaining:
            self.fail_create_remaining -= 1
            if self.persist_create_on_failure:
                self._add(title, body)
            raise filing.GithubError(502, "502 ghp_supersecretvalue")
        return self._add(title, body)

    def _add(self, title: str, body: str) -> dict:
        number = self.next_number
        self.next_number += 1
        issue = {
            "number": number,
            "node_id": f"ISSUE_{number}",
            "title": title,
            "body": body,
            "state": "open",
            "html_url": f"https://github.com/example/papers/issues/{number}",
        }
        self.issues.append(issue)
        return dict(issue)

    def project_item_id(self, node_id: str, project_id: str) -> str:
        self.calls.append("project_lookup")
        if self.fail_project_lookup_remaining:
            self.fail_project_lookup_remaining -= 1
            raise filing.GithubError(503, "503 ghp_supersecretvalue")
        return self.project_items.get((project_id, node_id), "")

    def add_project_item(self, project_id: str, node_id: str) -> str:
        self.calls.append("project_add")
        if self.snapshot_path is not None:
            self.snapshots.append(self.snapshot_path.read_text(encoding="utf-8"))
        if self.block_add:
            raise filing.GithubError(503, "503 ghp_supersecretvalue")
        if self.fail_project_add_remaining:
            self.fail_project_add_remaining -= 1
            if self.persist_add_on_failure:
                self.project_items[(project_id, node_id)] = "PVTI_saved"
            raise filing.GithubError(503, "503 ghp_supersecretvalue")
        self.project_items[(project_id, node_id)] = "PVTI_new"
        return "PVTI_new"


class ResumeTests(unittest.TestCase):
    def test_server_error_on_create_rechecks_and_does_not_create_again(self):
        store = make_store(Path(self.id_dir()), [pending("WP-0100", "https://example.org/a")])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.fail_create_remaining = 1
        fake.persist_create_on_failure = True
        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertEqual(fake.calls.count("create"), 1)
        create_at = fake.calls.index("create")
        self.assertIn("list", fake.calls[create_at + 1 :])
        self.assertNotIn("create", fake.calls[create_at + 1 :])
        self.assertEqual(store.data["items"][0]["status"], "done")
        self.assertEqual(store.data["items"][0]["issue_number"], 1)
        self.assertIn("<!-- wp-id: WP-0100 -->", fake.issues[0]["body"])
        self.assertNotIn("ghp_supersecretvalue", store.path.read_text(encoding="utf-8"))

    def test_failed_lookup_after_a_server_error_does_not_create_a_second_issue(self):
        directory = Path(self.id_dir())
        store = make_store(directory, [pending("WP-0101", "https://example.org/b")])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.fail_create_remaining = 1
        fake.persist_create_on_failure = True
        fake.lists_to_fail_after_create = filing.LOOKUP_ATTEMPTS
        with self.assertRaises(filing.GithubError):
            filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertEqual(fake.calls.count("create"), 1)
        self.assertEqual(store.data["items"][0]["status"], "pending")

        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertEqual(fake.calls.count("create"), 1)
        self.assertEqual(store.data["items"][0]["status"], "done")
        self.assertEqual(store.data["items"][0]["issue_number"], 1)
        self.assertEqual(len(fake.issues), 1)

    def test_clean_miss_after_a_server_error_rechecks_before_the_second_create(self):
        store = make_store(Path(self.id_dir()), [pending("WP-0102", "https://example.org/c")])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.fail_create_remaining = 1
        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        creates = [index for index, call in enumerate(fake.calls) if call == "create"]
        self.assertEqual(len(creates), 2)
        self.assertIn("list", fake.calls[creates[0] + 1 : creates[1]])

    def test_list_server_errors_do_not_create(self):
        store = make_store(Path(self.id_dir()), [pending("WP-0103", "https://example.org/d")])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.fail_list_remaining = 10
        with self.assertRaises(filing.GithubError):
            filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertNotIn("create", fake.calls)
        self.assertEqual(store.data["items"][0]["status"], "pending")

    def test_two_copies_of_a_marker_keep_the_lower_issue_number(self):
        item = pending("WP-0112", "https://example.org/dup-marker")
        body = filing.render_issue_body(item)
        store = make_store(Path(self.id_dir()), [item])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.issues = [
            {"number": 20, "node_id": "ISSUE_20", "title": "Later", "body": body, "state": "open"},
            {"number": 18, "node_id": "ISSUE_18", "title": "Earlier", "body": body, "state": "open"},
        ]
        fake.next_number = 21
        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertNotIn("create", fake.calls)
        self.assertEqual(store.data["items"][0]["issue_number"], 18)
        self.assertEqual(store.data["items"][0]["also_found"], [20])

    def test_existing_marker_is_not_created_again(self):
        item = pending("WP-0104", "https://example.org/e")
        store = make_store(Path(self.id_dir()), [item])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.issues.append(
            {
                "number": 50,
                "node_id": "ISSUE_50",
                "title": "Paper",
                "body": filing.render_issue_body(item),
                "state": "open",
            }
        )
        fake.next_number = 51
        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertNotIn("create", fake.calls)
        self.assertEqual(store.data["items"][0]["issue_number"], 50)
        self.assertEqual(store.data["items"][0]["status"], "done")
        self.assertEqual(store.data["created_issues"]["WP-0104"], 50)

    def test_existing_url_is_not_created_or_added_to_the_project(self):
        store = make_store(Path(self.id_dir()), [pending("WP-0105", "https://example.org/f")])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.issues.append(
            {
                "number": 7,
                "node_id": "ISSUE_7",
                "title": "Already there",
                "body": "**Source:** Example Lab\n**Link:** https://example.org/f\n",
                "state": "open",
            }
        )
        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertNotIn("create", fake.calls)
        self.assertNotIn("project_add", fake.calls)
        item = store.data["items"][0]
        self.assertEqual(item["status"], "already_filed")
        self.assertEqual(item["issue_number"], 7)
        self.assertNotIn("WP-0105", store.data["created_issues"])
        self.assertEqual(store.data["issues"]["WP-0105"], 7)

    def test_project_add_server_error_rechecks_before_a_second_add(self):
        store = make_store(Path(self.id_dir()), [pending("WP-0106", "https://example.org/g")])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.fail_project_add_remaining = 1
        fake.persist_add_on_failure = True
        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertEqual(fake.calls.count("project_add"), 1)
        self.assertEqual(store.data["items"][0]["project_item_id"], "PVTI_saved")
        self.assertEqual(store.data["items"][0]["status"], "done")

    def test_checkpoint_is_on_disk_before_the_project_add(self):
        store = make_store(Path(self.id_dir()), [pending("WP-0107", "https://example.org/h")])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.snapshot_path = store.path
        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertTrue(fake.snapshots)
        midway = json.loads(fake.snapshots[0])
        self.assertEqual(midway["items"][0]["status"], "issue_open")
        self.assertEqual(midway["items"][0]["issue_number"], 1)
        self.assertIn("WP-0107", midway["pending"])
        self.assertEqual(midway["created_issues"]["WP-0107"], 1)
        self.assertEqual(store.data["items"][0]["status"], "done")
        self.assertIn("WP-0107", store.data["done"])
        self.assertNotIn("WP-0107", store.data["pending"])

    def test_resume_finishes_the_project_item_and_does_not_create(self):
        store = make_store(Path(self.id_dir()), [pending("WP-0108", "https://example.org/i")])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.block_add = True
        with self.assertRaises(filing.GithubError):
            filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertEqual(fake.calls.count("create"), 1)
        reloaded = filing.RunStore.load(store.path)
        self.assertEqual(reloaded.data["items"][0]["status"], "issue_open")
        self.assertEqual(reloaded.data["pending"], ["WP-0108"])

        fake.block_add = False
        filing.file_batch(reloaded, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertEqual(fake.calls.count("create"), 1)
        self.assertEqual(reloaded.data["items"][0]["status"], "done")
        self.assertEqual(reloaded.data["created_issues"]["WP-0108"], 1)

    def test_batch_stops_and_the_next_run_continues(self):
        items = [
            pending("WP-0201", "https://example.org/batch-1"),
            pending("WP-0202", "https://example.org/batch-2"),
            pending("WP-0203", "https://example.org/batch-3"),
        ]
        store = make_store(Path(self.id_dir()), items)
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        first = filing.file_batch(store, fake, "PRJ", 2, sleep=lambda _seconds: None)
        self.assertEqual(first, 2)
        self.assertEqual(store.data["pending"], ["WP-0203"])
        self.assertEqual(fake.calls.count("create"), 2)
        filing.file_batch(store, fake, "PRJ", 2, sleep=lambda _seconds: None)
        self.assertEqual(store.data["pending"], [])
        self.assertEqual(fake.calls.count("create"), 3)
        creates_before = fake.calls.count("create")
        adds_before = fake.calls.count("project_add")
        again = filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertEqual(again, 0)
        self.assertEqual(fake.calls.count("create"), creates_before)
        self.assertEqual(fake.calls.count("project_add"), adds_before)

    def test_issue_open_is_finished_before_a_new_issue_is_created(self):
        opened = pending("WP-0301", "https://example.org/open")
        opened["status"] = "issue_open"
        opened["issue_number"] = 9
        opened["issue_node_id"] = "ISSUE_9"
        opened["created"] = True
        waiting = pending("WP-0302", "https://example.org/wait")
        store = make_store(Path(self.id_dir()), [opened, waiting])
        self.addCleanup(self._cleanup, store.path.parent)
        fake = FakeGitHub()
        fake.issues.append(
            {
                "number": 9,
                "node_id": "ISSUE_9",
                "title": "Paper",
                "body": filing.render_issue_body(opened),
                "state": "open",
            }
        )
        fake.next_number = 10
        filing.file_batch(store, fake, "PRJ", 1, sleep=lambda _seconds: None)
        self.assertNotIn("create", fake.calls)
        self.assertEqual(store.data["items"][0]["status"], "done")
        self.assertEqual(store.data["items"][1]["status"], "pending")

    def test_queue_reserves_ids_before_any_create(self):
        directory = Path(self.id_dir())
        store = make_store(directory, [])
        self.addCleanup(self._cleanup, store.path.parent)
        queue = [
            filing.normalize_queue_item(
                {"title": "Kept id", "source": "NIST", "url": "https://example.org/q2", "wp_id": "WP-0005"},
                1,
            ),
            filing.normalize_queue_item(
                {"title": "Next id", "source": "NIST", "url": "https://example.org/q1"},
                2,
            ),
        ]
        document = {"id_registry": [{"wp_id": "WP-0001", "url": "https://example.org/old", "issue_number": 1}]}
        filing.merge_queue(store, queue, document)
        filing.merge_queue(store, queue, document)
        self.assertEqual([item["wp_id"] for item in store.data["items"]], ["WP-0005", "WP-0002"])
        self.assertEqual([item["status"] for item in store.data["items"]], ["pending", "pending"])
        text = store.path.read_text(encoding="utf-8")
        self.assertIn("WP-0005", text)
        self.assertEqual(store.data["pending"], ["WP-0005", "WP-0002"])

    def test_registry_url_is_marked_already_filed(self):
        store = make_store(Path(self.id_dir()), [])
        self.addCleanup(self._cleanup, store.path.parent)
        queue = [
            filing.normalize_queue_item(
                {"title": "Known", "source": "NIST", "url": "https://example.org/old"},
                1,
            )
        ]
        document = {
            "id_registry": [
                {"wp_id": "WP-0004", "url": "https://example.org/old", "issue_number": 4}
            ]
        }
        filing.merge_queue(store, queue, document)
        self.assertEqual(store.data["items"][0]["status"], "already_filed")
        self.assertEqual(store.data["items"][0]["issue_number"], 4)
        self.assertEqual(store.data["items"][0]["wp_id"], "WP-0004")
        fake = FakeGitHub()
        filing.file_batch(store, fake, "PRJ", 25, sleep=lambda _seconds: None)
        self.assertEqual(fake.calls, [])

    def test_rendered_body_round_trips_through_the_export(self):
        item = pending("WP-0109", "https://example.org/round-trip", title="Round trip paper")
        item["arxiv_id"] = "2305.18447"
        item["cited_by"] = "#26 Example"
        item["evidence_level"] = "tested"
        body = filing.render_issue_body(item)
        document = inventory.build_inventory(
            [
                {
                    "number": 12,
                    "title": item["title"],
                    "state": "open",
                    "html_url": "https://github.com/example/papers/issues/12",
                    "body": body,
                }
            ],
            updated="2026-11-04",
            repository="example/papers",
        )
        paper = document["papers"][0]
        self.assertEqual(paper["wp_id"], "WP-0109")
        self.assertEqual(paper["source_org"], "Example Lab")
        self.assertEqual(paper["url"], "https://example.org/round-trip")
        self.assertEqual(paper["axioms"], [])
        self.assertIn("2305.18447", paper["legacy_notes"])

    def test_run_file_cannot_be_written_under_raw(self):
        path = ROOT / "raw" / "2026-11-04.json"
        with self.assertRaises(SystemExit) as caught:
            filing.RunStore.create(
                path,
                date="2026-11-04",
                repository="example/papers",
                project_owner="example",
                project_number=2,
                batch_size=25,
            )
        self.assertIn("read-only", str(caught.exception))
        self.assertFalse(path.exists())

    def test_latest_pointer_resumes_a_pending_run_on_a_later_day(self):
        directory = Path(self.id_dir())
        store = make_store(directory, [pending("WP-0110", "https://example.org/later")])
        self.addCleanup(self._cleanup, store.path.parent)
        self.assertEqual((store.path.parent / "latest.txt").read_text(encoding="utf-8").strip(), "2026-11-04")
        resolved = filing.resolve_run_path(root=directory)
        self.assertEqual(resolved, store.path)
        rolled = filing.roll_completed_run(resolved, have_queue=True, pinned=False)
        self.assertEqual(rolled, store.path)

    def test_a_finished_run_plus_a_new_queue_starts_a_new_file(self):
        directory = Path(self.id_dir())
        item = pending("WP-0111", "https://example.org/finished")
        item["status"] = "done"
        item["issue_number"] = 3
        item["created"] = True
        store = make_store(directory, [item], date="2026-11-03")
        self.addCleanup(self._cleanup, store.path.parent)
        rolled = filing.roll_completed_run(store.path, have_queue=True, pinned=False)
        self.assertEqual(rolled.name, f"{filing.utc_today()}.json")
        pinned = filing.roll_completed_run(store.path, have_queue=True, pinned=True)
        self.assertEqual(pinned, store.path)

    def id_dir(self) -> str:
        import tempfile

        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: None)
        return directory

    def _cleanup(self, runs: Path) -> None:
        import shutil

        parent = runs.parent
        if parent.exists() and str(parent).startswith("/tmp/"):
            shutil.rmtree(parent, ignore_errors=True)


class ClientTests(unittest.TestCase):
    def test_server_error_hides_the_token(self):
        token = "ghp_supersecretvalue"

        def opener(request, timeout=60):
            raise urllib.error.HTTPError(
                request.full_url,
                502,
                "Bad Gateway",
                EmailMessage(),
                io.BytesIO(f"upstream failed {token}".encode()),
            )

        client = filing.GithubRestClient("example/papers", issue_token=token, project_token=token, opener=opener)
        with self.assertRaises(filing.GithubError) as caught:
            client.list_issues()
        self.assertNotIn(token, str(caught.exception))
        self.assertIn("[redacted]", str(caught.exception))

    def test_timeout_is_a_server_error(self):
        def opener(request, timeout=60):
            raise urllib.error.URLError(TimeoutError("timed out"))

        client = filing.GithubRestClient("example/papers", issue_token="ghp_supersecretvalue", opener=opener)
        with self.assertRaises(filing.GithubError) as caught:
            client.list_issues()
        self.assertEqual(caught.exception.status, 504)

    def test_create_sends_title_and_body_only(self):
        token = "ghp_supersecretvalue"
        seen = {}

        def opener(request, timeout=60):
            seen["method"] = request.get_method()
            seen["payload"] = json.loads(request.data.decode())
            seen["authorization"] = request.get_header("Authorization")
            body = seen["payload"]["body"]
            return FakeResponse({"number": 4, "node_id": "ISSUE_4", "title": seen["payload"]["title"], "body": body})

        client = filing.GithubRestClient("example/papers", issue_token=token, opener=opener)
        issue = client.create_issue("Title", "<!-- wp-id: WP-0008 -->\n\n**Source:** NIST\n")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(set(seen["payload"]), {"title", "body"})
        self.assertNotIn(token, json.dumps(seen["payload"]))
        self.assertEqual(issue["number"], 4)
        self.assertTrue(seen["authorization"].startswith("Bearer "))

    def test_network_guard_stops_before_a_call(self):
        previous = os.environ.get(filing.NETWORK_GUARD)
        os.environ[filing.NETWORK_GUARD] = "1"
        try:
            client = filing.GithubRestClient("example/papers", issue_token="ghp_supersecretvalue")
            with self.assertRaises(SystemExit):
                client.create_issue("Title", "body")
        finally:
            if previous is None:
                os.environ.pop(filing.NETWORK_GUARD, None)
            else:
                os.environ[filing.NETWORK_GUARD] = previous

    def test_filing_source_does_not_close_or_print_tokens(self):
        text = (ROOT / "scripts" / "filing.py").read_text(encoding="utf-8")
        text += (ROOT / "scripts" / "file_issues.py").read_text(encoding="utf-8")
        pr = (ROOT / "scripts" / "open_inventory_pr.py").read_text(encoding="utf-8")
        for banned in ("DELETE", "--force", "push origin master", "state=closed"):
            self.assertNotIn(banned, text)
            self.assertNotIn(banned, pr)
        in_docstring = False
        for line in text.splitlines():
            if line.count('"""') == 1:
                in_docstring = not in_docstring
                continue
            if line.count('"""') >= 2 or in_docstring or line.strip().startswith("#"):
                continue
            if "GITHUB_PROJECTS_TOKEN" in line:
                self.assertIn("os.environ", line)


class PullRequestGuardTests(unittest.TestCase):
    def test_push_command_refuses_the_default_branch_and_has_no_force_flag(self):
        for branch in ("master", "main", "HEAD"):
            with self.assertRaises(SystemExit):
                open_inventory_pr.push_command(branch)
        command = open_inventory_pr.push_command("weekly/2026-11-04")
        self.assertEqual(command, ["git", "push", "-u", "origin", "weekly/2026-11-04"])
        self.assertNotIn("--force", command)
        self.assertNotIn("--force-with-lease", command)

    def test_pr_command_targets_master(self):
        command = open_inventory_pr.pr_command("Weekly pass", "Body")
        self.assertEqual(command[0:4], ["gh", "pr", "create", "--base"])
        self.assertIn("master", command)
        self.assertNotIn("--force", command)


class CommandTests(unittest.TestCase):
    def test_dry_run_writes_a_checkpoint_and_does_not_call_github(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "queue.json"
            run = Path(tmp) / "run.json"
            queue.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "title": "Probe paper",
                                "source": "NIST",
                                "url": "https://example.org/weekly-pass-reliability-probe",
                                "summary": "A public guidance paper.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env[filing.NETWORK_GUARD] = "1"
            env.pop("GITHUB_TOKEN", None)
            env.pop("GH_TOKEN", None)
            env.pop("GITHUB_PROJECTS_TOKEN", None)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "file_issues.py"),
                    "run",
                    "--queue",
                    str(queue),
                    "--run",
                    str(run),
                    "--dry-run",
                    "--batch-size",
                    "25",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("GitHub was not contacted.", completed.stdout)
            saved = json.loads(run.read_text(encoding="utf-8"))
            self.assertEqual(saved["items"][0]["status"], "pending")
            self.assertEqual(saved["pending"], [saved["items"][0]["wp_id"]])
            self.assertEqual(saved["created_issues"], {})
            self.assertNotIn("ghp_", run.read_text(encoding="utf-8"))
            again = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "file_issues.py"),
                    "run",
                    "--queue",
                    str(queue),
                    "--run",
                    str(run),
                    "--dry-run",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(again.returncode, 0, again.stderr)
            saved_again = json.loads(run.read_text(encoding="utf-8"))
            self.assertEqual(len(saved_again["items"]), 1)

    def test_schema_only_does_not_list_issues(self):
        import validate_whitepapers

        called = []
        original = validate_whitepapers.inventory.fetch_issues
        validate_whitepapers.inventory.fetch_issues = lambda *args, **kwargs: called.append("fetch") or []
        argv = sys.argv
        stdout = io.StringIO()
        try:
            sys.argv = ["validate_whitepapers.py", "--schema-only"]
            with contextlib.redirect_stdout(stdout):
                validate_whitepapers.main()
        finally:
            sys.argv = argv
            validate_whitepapers.inventory.fetch_issues = original
        self.assertEqual(called, [])
        self.assertIn("schema ok", stdout.getvalue())

    def test_missing_jsonschema_names_the_install_command(self):
        import builtins

        import validate_whitepapers

        real_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "jsonschema":
                raise ImportError("no jsonschema")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = guarded
        try:
            with self.assertRaises(SystemExit) as caught:
                validate_whitepapers.check_schema({"version": 1})
        finally:
            builtins.__import__ = real_import
        self.assertIn("scripts/requirements.txt", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
