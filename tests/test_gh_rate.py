#!/usr/bin/env python3
"""GitHub rate limits: backoff, the write budget, and no duplicate create."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import filing  # noqa: E402
import gh_rate  # noqa: E402


class Ticker:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(float(seconds))
        self.now += float(seconds)


class FakeResponse:
    def __init__(self, payload, status: int = 200, headers: dict | None = None):
        self.raw = json.dumps(payload).encode()
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self.raw

    def close(self) -> None:
        return None


def limiter(ticker: Ticker, directory: Path | None = None, **overrides) -> gh_rate.Limiter:
    settings = {
        "write_delay": 0,
        "hourly_budget": 400,
        "max_retries": 4,
        "sleep": ticker.sleep,
        "clock": ticker.time,
        "log": lambda _message: None,
        "state_path": None if directory is None else directory / "gh-write-log.json",
    }
    settings.update(overrides)
    return gh_rate.Limiter(**settings)


def ok(body: str = "{}") -> gh_rate.HttpResult:
    return gh_rate.HttpResult(200, {"X-RateLimit-Remaining": "4999"}, body)


class BackoffTests(unittest.TestCase):
    def test_403_secondary_limit_waits_then_backs_off(self):
        ticker = Ticker()
        logs: list[str] = []
        calls = {"n": 0}

        def send():
            calls["n"] += 1
            if calls["n"] < 3:
                return gh_rate.HttpResult(
                    403,
                    {
                        "X-RateLimit-Remaining": "4900",
                        "X-RateLimit-Limit": "5000",
                        "X-RateLimit-Reset": str(int(ticker.now + 500)),
                        "X-RateLimit-Resource": "core",
                    },
                    '{"message":"You have exceeded a secondary rate limit."}',
                )
            return ok()

        result = limiter(ticker, log=logs.append).execute(send, write=True)
        self.assertEqual(result.status, 200)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(ticker.slept, [60.0, 120.0])
        self.assertTrue(any("remaining=4900" in line for line in logs))
        self.assertTrue(any("limit=5000" in line for line in logs))

    def test_429_honors_retry_after(self):
        ticker = Ticker()
        calls = {"n": 0}

        def send():
            calls["n"] += 1
            if calls["n"] == 1:
                return gh_rate.HttpResult(
                    429,
                    {"Retry-After": "9", "X-RateLimit-Remaining": "100"},
                    "slow down",
                )
            return ok()

        result = limiter(ticker).execute(send, write=True)
        self.assertEqual(result.status, 200)
        self.assertEqual(ticker.slept, [9.0])
        self.assertLess(ticker.slept[0], 60)

    def test_primary_limit_waits_until_reset(self):
        ticker = Ticker()
        calls = {"n": 0}
        reset = ticker.now + 25

        def send():
            calls["n"] += 1
            if calls["n"] == 1:
                return gh_rate.HttpResult(
                    403,
                    {
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(reset)),
                        "X-RateLimit-Resource": "core",
                    },
                    "API rate limit exceeded",
                )
            return gh_rate.HttpResult(200, {"X-RateLimit-Remaining": "5000"}, "{}")

        result = limiter(ticker).execute(send, write=False)
        self.assertEqual(result.status, 200)
        self.assertEqual(ticker.slept, [25.0])
        self.assertLess(ticker.slept[0], gh_rate.MIN_LIMIT_WAIT)

    def test_retries_stop_after_the_cap(self):
        ticker = Ticker()
        calls = {"n": 0}

        def send():
            calls["n"] += 1
            return gh_rate.HttpResult(403, {"X-RateLimit-Remaining": "10"}, "secondary")

        with self.assertRaises(gh_rate.RetryGaveUp) as caught:
            limiter(ticker, max_retries=2).execute(send, write=False)
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(ticker.slept, [60.0, 120.0])

    def test_404_is_not_retried(self):
        ticker = Ticker()
        calls = {"n": 0}

        def send():
            calls["n"] += 1
            return gh_rate.HttpResult(404, {}, "missing")

        result = limiter(ticker).execute(send, write=False)
        self.assertEqual(result.status, 404)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(ticker.slept, [])

    def test_requests_run_one_at_a_time(self):
        overlap = {"inside": 0, "hit": False}
        probe = threading.Lock()

        def send():
            with probe:
                overlap["inside"] += 1
                if overlap["inside"] > 1:
                    overlap["hit"] = True
            try:
                threading.Event().wait(0.05)
            finally:
                with probe:
                    overlap["inside"] -= 1
            return ok()

        gate = gh_rate.Limiter(
            write_delay=0,
            max_retries=0,
            sleep=lambda _seconds: None,
            log=lambda _message: None,
            state_path=None,
        )
        start = threading.Barrier(2)

        def run():
            start.wait()
            gate.execute(send, write=False)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(overlap["hit"])


class BudgetTests(unittest.TestCase):
    def test_hourly_budget_stops_and_the_next_limiter_sees_it(self):
        ticker = Ticker()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            calls = {"n": 0}

            def send():
                calls["n"] += 1
                return gh_rate.HttpResult(201, {"X-RateLimit-Remaining": "50"}, "{}")

            first = limiter(ticker, directory, hourly_budget=2)
            first.execute(send, write=True)
            first.execute(send, write=True)
            with self.assertRaises(gh_rate.WriteBudgetExceeded) as caught:
                first.execute(send, write=True)
            self.assertEqual(calls["n"], 2)
            self.assertEqual(caught.exception.budget, 2)
            self.assertEqual(caught.exception.used, 2)
            self.assertIn("Resume at", str(caught.exception))
            text = (directory / "gh-write-log.json").read_text(encoding="utf-8")
            self.assertNotIn("ghp_", text)
            self.assertNotIn("GITHUB", text)
            self.assertNotIn("token", text.lower())

            second = limiter(ticker, directory, hourly_budget=2)
            with self.assertRaises(gh_rate.WriteBudgetExceeded):
                second.execute(send, write=True)
            self.assertEqual(calls["n"], 2)

            ticker.now += gh_rate.HOUR_SECONDS
            third = limiter(ticker, directory, hourly_budget=2)
            third.execute(send, write=True)
            self.assertEqual(calls["n"], 3)

    def test_budget_cutoff_saves_the_run_file_and_resume_does_not_create_again(self):
        ticker = Ticker()
        logs: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            seen = {"create": 0, "mutation": 0}
            raw = filing.normalize_queue_item(
                {
                    "title": "Budget paper",
                    "source": "Example Lab",
                    "url": "https://example.org/budget-paper",
                    "summary": "A public guidance paper.",
                    "date_published": "March 2026",
                },
                1,
            )
            item = filing.new_item(raw, "WP-0200", status="pending", issue_number=None)
            store = filing.RunStore.create(
                directory / "runs" / "2026-11-04.json",
                date="2026-11-04",
                repository="example/papers",
                project_owner="example",
                project_number=2,
                batch_size=25,
            )
            store.data["items"] = [item]
            store.save()

            def opener(request, timeout=60):
                method = request.get_method()
                url = request.full_url
                data = request.data or b""
                if method == "GET":
                    return FakeResponse([], 200)
                if method == "POST" and url.rstrip("/").endswith("/issues"):
                    seen["create"] += 1
                    payload = json.loads(data.decode())
                    return FakeResponse(
                        {
                            "number": 41,
                            "node_id": "NODE41",
                            "title": payload["title"],
                            "body": payload["body"],
                            "state": "open",
                        },
                        201,
                        {
                            "X-RateLimit-Remaining": "4800",
                            "X-RateLimit-Limit": "5000",
                            "X-RateLimit-Resource": "core",
                        },
                    )
                if method == "POST" and url.endswith("/graphql"):
                    if b"mutation" in data[:80]:
                        seen["mutation"] += 1
                        return FakeResponse(
                            {"data": {"addProjectV2ItemById": {"item": {"id": "PVTI_1"}}}},
                            200,
                        )
                    return FakeResponse(
                        {"data": {"node": {"projectItems": {"nodes": []}}}},
                        200,
                    )
                raise AssertionError(f"{method} {url}")

            token = "ghp_supersecretvalue"
            gate = limiter(ticker, directory, hourly_budget=1, log=logs.append)
            client = filing.GithubRestClient(
                "example/papers",
                issue_token=token,
                project_token=token,
                opener=opener,
                limiter=gate,
            )
            with self.assertRaises(gh_rate.WriteBudgetExceeded):
                filing.file_batch(store, client, "PRJ", 25, sleep=lambda _seconds: None)
            disk = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(disk["items"][0]["status"], "issue_open")
            self.assertEqual(disk["items"][0]["issue_number"], 41)
            self.assertEqual(disk["items"][0]["issue_node_id"], "NODE41")
            self.assertEqual(disk["pending"], ["WP-0200"])
            self.assertFalse(disk["items"][0].get("project_item_id"))
            self.assertEqual(seen["create"], 1)
            self.assertEqual(seen["mutation"], 0)
            self.assertNotIn(token, store.path.read_text(encoding="utf-8"))
            self.assertNotIn(token, (directory / "gh-write-log.json").read_text(encoding="utf-8"))
            self.assertTrue(any("remaining=4800" in line for line in logs))

            ticker.now += gh_rate.HOUR_SECONDS
            resumed = limiter(ticker, directory, hourly_budget=1, log=lambda _message: None)
            client.limiter = resumed
            filing.file_batch(store, client, "PRJ", 25, sleep=lambda _seconds: None)
            self.assertEqual(store.data["items"][0]["status"], "done")
            self.assertEqual(store.data["items"][0]["project_item_id"], "PVTI_1")
            self.assertEqual(seen["create"], 1)
            self.assertEqual(seen["mutation"], 1)


class DuplicateTests(unittest.TestCase):
    def test_dropped_connection_mid_create_does_not_post_again(self):
        ticker = Ticker()
        created: dict = {}
        posts = {"n": 0}

        def opener(request, timeout=60):
            if request.get_method() == "POST" and request.full_url.rstrip("/").endswith("/issues"):
                posts["n"] += 1
                payload = json.loads(request.data.decode())
                created["issue"] = {
                    "number": 9,
                    "node_id": "ISSUE_9",
                    "title": payload["title"],
                    "body": payload["body"],
                    "state": "open",
                }
                raise urllib.error.URLError(ConnectionResetError("connection dropped"))
            if request.get_method() == "GET":
                body = [created["issue"]] if created.get("issue") else []
                return FakeResponse(body, 200)
            raise AssertionError(request.full_url)

        client = filing.GithubRestClient(
            "example/papers",
            issue_token="ghp_supersecretvalue",
            opener=opener,
            limiter=limiter(ticker, max_retries=2, hourly_budget=10),
        )
        issue = client.create_issue(
            "Title",
            "<!-- wp-id: WP-0100 -->\n\n**Source:** Example Lab\n**Link:** https://example.org/a\n",
        )
        self.assertEqual(posts["n"], 1)
        self.assertEqual(issue["number"], 9)
        self.assertIn("<!-- wp-id: WP-0100 -->", issue["body"])
        self.assertEqual(ticker.slept, [])

    def test_lookup_failure_does_not_send_the_create_again(self):
        ticker = Ticker()
        calls = {"n": 0}

        def send():
            calls["n"] += 1
            raise gh_rate.TransportError("connection dropped", 503)

        def before_retry():
            raise gh_rate.DoNotRetry()

        with self.assertRaises(gh_rate.RetryGaveUp):
            limiter(ticker, max_retries=3).execute(send, write=True, before_retry=before_retry)
        self.assertEqual(calls["n"], 1)


class CliTests(unittest.TestCase):
    def test_cli_429_waits_for_retry_after(self):
        ticker = Ticker()
        calls = {"n": 0}

        def runner(argv, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return subprocess.CompletedProcess(argv, 1, "", "HTTP 429\nRetry-After: 3\n")
            return subprocess.CompletedProcess(argv, 0, "https://github.com/example/pull/1\n", "")

        stdout = gh_rate.run_github_cli(
            ["gh", "pr", "create", "--title", "Weekly"],
            write=True,
            cwd=ROOT,
            limiter=limiter(ticker, max_retries=2),
            runner=runner,
            echo=False,
        )
        self.assertEqual(calls["n"], 2)
        self.assertEqual(ticker.slept, [3.0])
        self.assertIn("pull/1", stdout)

    def test_from_env_defaults_and_rejects_a_fast_or_large_budget(self):
        keys = ("GITHUB_WRITE_DELAY", "GITHUB_HOURLY_WRITE_BUDGET", "GITHUB_RATE_MAX_RETRIES")
        saved = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ.pop(key, None)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "gh-write-log.json"
                built = gh_rate.Limiter.from_env(state_path=path)
                self.assertEqual(built.write_delay, 1.0)
                self.assertEqual(built.hourly_budget, 400)
                self.assertEqual(built.max_retries, 5)
                with self.assertRaises(SystemExit):
                    gh_rate.Limiter.from_env(write_delay=0.5, state_path=path)
                with self.assertRaises(SystemExit):
                    gh_rate.Limiter.from_env(hourly_budget=500, state_path=path)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_weekly_batch_fits_and_help_lists_the_flags(self):
        writes = filing.DEFAULT_BATCH_SIZE * 2
        self.assertLessEqual(writes, gh_rate.DEFAULT_HOURLY_WRITE_BUDGET)
        self.assertLessEqual(gh_rate.DEFAULT_HOURLY_WRITE_BUDGET, gh_rate.MAX_HOURLY_WRITE_BUDGET)
        self.assertLess(gh_rate.MAX_HOURLY_WRITE_BUDGET, 500)
        self.assertGreaterEqual(gh_rate.DEFAULT_WRITE_DELAY, 1)
        per_minute = 60 / gh_rate.DEFAULT_WRITE_DELAY
        self.assertLessEqual(per_minute, 80)
        self.assertLessEqual(per_minute * 5, 900)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "file_issues.py"), "run", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--write-delay", completed.stdout)
        self.assertIn("--write-budget", completed.stdout)

    def test_gh_404_is_not_retried_and_stays_a_missing_issue(self):
        calls = {"n": 0}

        def runner(command, **_kwargs):
            calls["n"] += 1
            return subprocess.CompletedProcess(
                command,
                1,
                "HTTP/2.0 404 Not Found\n\n{\"message\":\"Not Found\"}\n",
                "",
            )

        client = filing.GithubRestClient(
            "example/papers",
            runner=runner,
            limiter=gh_rate.Limiter(
                write_delay=0,
                max_retries=3,
                sleep=lambda _seconds: None,
                log=lambda _message: None,
                state_path=None,
            ),
        )
        with self.assertRaises(filing.GithubError) as caught:
            client.get_issue(9)
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(calls["n"], 1)

    def test_split_include_reads_remaining(self):
        status, headers, body = gh_rate.split_include(
            "HTTP/2.0 200 OK\nX-RateLimit-Remaining: 12\nX-RateLimit-Resource: core\n\n{\"ok\": true}\n"
        )
        self.assertEqual(status, 200)
        self.assertEqual(gh_rate.header_value(headers, "x-ratelimit-remaining"), "12")
        self.assertIn("ok", body)


if __name__ == "__main__":
    unittest.main()
