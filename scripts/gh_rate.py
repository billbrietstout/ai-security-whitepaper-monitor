#!/usr/bin/env python3
"""Pace and retry GitHub REST and GraphQL calls.

GitHub's published limits for an authenticated token:

- 5,000 requests an hour on the primary limit.
- 80 content-creating requests a minute, and 500 an hour. Issue creates,
  comments, edits, and project mutations count toward that secondary limit.
- 900 points a minute on each REST endpoint. A write costs 5 points.
- 2,000 points a minute on GraphQL. A mutation costs 5 points.
- 100 concurrent requests.

This module sends one request at a time. Content-creating calls wait at
least one second apart (configurable, never faster than that through
``from_env``). The hourly write budget defaults to 400, under the 500
write cap. At the budget the caller gets ``WriteBudgetExceeded`` and can
save its checkpoint. The next run on this checkout reads
``runs/gh-write-log.json`` and will not start another full budget in the
same hour.

On 403, 429, 5xx, timeouts, and dropped connections the helper waits and
retries. ``Retry-After`` wins. If ``X-RateLimit-Remaining`` is 0, the wait
runs until ``X-RateLimit-Reset``. Otherwise the wait is 60 seconds and
then doubles, and the helper stops after a fixed number of retries.

A create passes ``before_retry``. That callback lists issues and looks for
the ``<!-- wp-id: WP-0000 -->`` marker. When the marker is already there,
the helper returns the existing issue and does not POST again.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WRITE_DELAY = 1.0
DEFAULT_HOURLY_WRITE_BUDGET = 400
MAX_HOURLY_WRITE_BUDGET = 450
DEFAULT_MAX_RETRIES = 5
MAX_RETRIES_CAP = 8
MIN_LIMIT_WAIT = 60
HOUR_SECONDS = 3600
MAX_WAIT = HOUR_SECONDS + MIN_LIMIT_WAIT

ROOT = Path(__file__).resolve().parents[1]
STATE_NAME = "gh-write-log.json"

_STATUS_RE = re.compile(r"HTTP(?:/\d(?:\.\d)?)?\s+(\d{3})")
_RATE_HEADER_NAMES = {
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-ratelimit-resource",
    "x-ratelimit-used",
}
_shared: "Limiter | None" = None


class TransportError(Exception):
    """The TCP call did not return an HTTP status."""

    def __init__(self, message: str, status: int = 503):
        self.status = status
        super().__init__(message)


class DoNotRetry(Exception):
    """The pre-retry check could not prove that another write is safe."""


class CommandFailed(Exception):
    """A GitHub CLI command failed for a reason that is not a rate limit."""


class WriteBudgetExceeded(Exception):
    """The local hourly write budget is spent. The checkpoint should be kept."""

    def __init__(self, budget: int, used: int, retry_at: float):
        self.budget = budget
        self.used = used
        self.retry_at = retry_at
        when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(retry_at))
        super().__init__(
            f"Hourly GitHub write budget of {budget} is spent "
            f"({used} writes in the last hour). "
            f"Resume at {when}. The run file is saved."
        )


class RetryGaveUp(Exception):
    """Retries for a rate limit or a transport error are used up."""

    def __init__(self, status: int, message: str):
        self.status = int(status or 0)
        self.message = (message or "")[:500]
        super().__init__(self.message)


@dataclass
class HttpResult:
    status: int
    headers: object
    body: str
    recovered: object = None


def default_state_path() -> Path:
    return ROOT / "runs" / STATE_NAME


def header_value(headers, name: str) -> str:
    if not headers:
        return ""
    target = name.lower()
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == target and value is not None:
                return str(value).strip()
        return ""
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    for candidate in (name, target):
        value = getter(candidate)
        if value:
            return str(value).strip()
    return ""


def _header_int(headers, name: str) -> int | None:
    raw = header_value(headers, name)
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _safe_field(value: str, *, digits: bool) -> str:
    if digits:
        return value if value.isdigit() and len(value) <= 12 else ""
    if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value or ""):
        return value
    return ""


def _retryable_status(status: int) -> bool:
    return status in (403, 429) or 500 <= status <= 599


def status_from_text(text: str) -> int:
    match = _STATUS_RE.search(text or "")
    if not match:
        return 0
    return int(match.group(1))


def _headers_from_text(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        name = key.strip().lower()
        if name in _RATE_HEADER_NAMES:
            found[name] = value.strip()
    return found


def split_include(raw: str) -> tuple[int, dict[str, str], str]:
    """Split one `gh api --include` body into status, headers, and payload."""
    text = raw or ""
    stripped = text.lstrip()
    if not stripped.startswith("HTTP/"):
        return 0, {}, text
    parts = re.split(r"(?=HTTP/\d(?:\.\d)? )", stripped)
    blocks = [part for part in parts if part.startswith("HTTP/")]
    block = blocks[-1] if blocks else stripped
    if "\r\n\r\n" in block:
        header_text, body = block.split("\r\n\r\n", 1)
    elif "\n\n" in block:
        header_text, body = block.split("\n\n", 1)
    else:
        header_text, body = block, ""
    lines = header_text.splitlines()
    status = status_from_text(lines[0] if lines else "")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return status, headers, body


def redact(text: str, secrets: list[str]) -> str:
    cleaned = text or ""
    for secret in secrets:
        if secret and len(secret) >= 8:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def _env_secrets(env: dict[str, str] | None) -> list[str]:
    source_token = os.environ.get("GITHUB_TOKEN", "") if env is None else env.get("GITHUB_TOKEN", "")
    source_gh = os.environ.get("GH_TOKEN", "") if env is None else env.get("GH_TOKEN", "")
    source_projects = os.environ.get("GITHUB_PROJECTS_TOKEN", "") if env is None else env.get("GITHUB_PROJECTS_TOKEN", "")
    source_site = os.environ.get("SITE_REPO_TOKEN", "") if env is None else env.get("SITE_REPO_TOKEN", "")
    return [value for value in (source_token, source_gh, source_projects, source_site) if value]


def result_from_process(returncode: int, stdout: str, stderr: str) -> HttpResult:
    """Turn a gh CLI result into an HTTP result the limiter can retry."""
    status, headers, body = split_include(stdout)
    text_headers = _headers_from_text(f"{stdout}\n{stderr}")
    for key, value in text_headers.items():
        headers.setdefault(key, value)
    if status == 0:
        status = status_from_text(f"{stdout}\n{stderr}")
    combined = f"{stdout}\n{stderr}".lower()
    if returncode == 0 and status in (0, 200, 201, 204):
        if status == 0:
            return HttpResult(200, headers, stdout)
        return HttpResult(status, headers, body if body else stdout)
    if status:
        return HttpResult(status, headers, body or stderr or stdout)
    if "rate limit" in combined:
        return HttpResult(status or 429, headers, stderr or stdout)
    if "timeout" in combined or "timed out" in combined:
        return HttpResult(504, headers, stderr or stdout)
    if any(
        word in combined
        for word in (
            "connection reset",
            "connection refused",
            "connection dropped",
            "connection aborted",
            "temporarily unavailable",
            "server error",
        )
    ):
        return HttpResult(status or 503, headers, stderr or stdout)
    if returncode == 0:
        return HttpResult(status or 200, headers, body or stdout)
    message = (stderr or stdout or "GitHub command failed.").strip()
    raise CommandFailed(message)


def retry_after_seconds(headers, now: float) -> float | None:
    raw = header_value(headers, "retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    return max(0.0, parsed.timestamp() - now)


def perform_urllib(opener, request, timeout: int = 60) -> HttpResult:
    """Run one urllib call. HTTP error statuses come back as results."""
    try:
        response = opener(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return HttpResult(int(exc.code or 0), exc.headers, detail)
    except TimeoutError:
        raise TransportError("GitHub API timed out.", 504) from None
    except urllib.error.URLError as exc:
        reason = exc.reason
        text = str(reason)
        lowered = text.lower()
        if isinstance(reason, TimeoutError) or "timed out" in lowered or "timeout" in lowered:
            raise TransportError("GitHub API timed out.", 504) from None
        raise TransportError(f"GitHub API connection failed: {text}", 503) from None
    except OSError as exc:
        raise TransportError(f"GitHub API connection failed: {exc}", 503) from None
    try:
        raw = response.read().decode("utf-8", errors="replace")
        status = int(getattr(response, "status", 200) or 200)
        headers = getattr(response, "headers", {}) or {}
    finally:
        close = getattr(response, "close", None)
        if close:
            close()
    return HttpResult(status, headers, raw)


def _default_log(message: str) -> None:
    print(message, file=sys.stderr)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"{name} must be a number of seconds.") from None


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit():
        raise SystemExit(f"{name} must be a positive integer.")
    return int(raw)


class Limiter:
    """Serial GitHub calls, a write budget, and the documented backoff."""

    def __init__(
        self,
        *,
        write_delay: float = DEFAULT_WRITE_DELAY,
        hourly_budget: int = DEFAULT_HOURLY_WRITE_BUDGET,
        max_retries: int = DEFAULT_MAX_RETRIES,
        min_limit_wait: int = MIN_LIMIT_WAIT,
        sleep=time.sleep,
        clock=time.time,
        log=None,
        state_path: Path | None = None,
    ):
        if write_delay < 0:
            raise ValueError("write_delay must be >= 0")
        if hourly_budget < 1:
            raise ValueError("hourly_budget must be >= 1")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.write_delay = float(write_delay)
        self.hourly_budget = int(hourly_budget)
        self.max_retries = int(max_retries)
        self.min_limit_wait = int(min_limit_wait)
        self.max_wait = float(MAX_WAIT)
        self.sleep = sleep
        self.clock = clock
        self.log = log or _default_log
        self._thread = threading.RLock()
        self._depth = 0
        self._blocked_until = 0.0
        self._memory_writes: list[float] = []
        self._fd = None
        if state_path is None:
            self.state_path = None
        else:
            self.state_path = Path(state_path)
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = Path(str(self.state_path) + ".lock")
            self._fd = open(lock_path, "a+", encoding="utf-8")

    def close(self) -> None:
        fd = self._fd
        self._fd = None
        if fd is not None:
            fd.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return

    @classmethod
    def from_env(
        cls,
        *,
        write_delay: float | None = None,
        hourly_budget: int | None = None,
        max_retries: int | None = None,
        state_path: Path | None = None,
        sleep=time.sleep,
        clock=time.time,
        log=None,
    ) -> "Limiter":
        """Build the limiter the scripts use. Rejects a pace that can pass 80 writes a minute."""
        if write_delay is None:
            delay = _env_float("GITHUB_WRITE_DELAY", DEFAULT_WRITE_DELAY)
        else:
            delay = float(write_delay)
        if hourly_budget is None:
            budget = _env_int("GITHUB_HOURLY_WRITE_BUDGET", DEFAULT_HOURLY_WRITE_BUDGET)
        else:
            budget = int(hourly_budget)
        if max_retries is None:
            retries = _env_int("GITHUB_RATE_MAX_RETRIES", DEFAULT_MAX_RETRIES)
        else:
            retries = int(max_retries)
        if delay < DEFAULT_WRITE_DELAY:
            raise SystemExit(
                "GITHUB_WRITE_DELAY must be at least 1 second. "
                "A faster pace can pass 80 content-creating requests a minute."
            )
        if not 1 <= budget <= MAX_HOURLY_WRITE_BUDGET:
            raise SystemExit(
                "GITHUB_HOURLY_WRITE_BUDGET must be from 1 to 450. "
                "The default is 400, under GitHub's 500 writes an hour."
            )
        if not 1 <= retries <= MAX_RETRIES_CAP:
            raise SystemExit("GITHUB_RATE_MAX_RETRIES must be from 1 to 8.")
        if state_path is None:
            state_path = default_state_path()
        return cls(
            write_delay=delay,
            hourly_budget=budget,
            max_retries=retries,
            sleep=sleep,
            clock=clock,
            log=log,
            state_path=state_path,
        )

    @contextmanager
    def _guard(self):
        self._thread.acquire()
        acquired_file = False
        try:
            if self._depth == 0 and self._fd is not None:
                fcntl.flock(self._fd, fcntl.LOCK_EX)
                acquired_file = True
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if acquired_file and self._fd is not None:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            self._thread.release()

    def execute(self, send, *, write: bool = False, before_retry=None) -> HttpResult:
        """Run ``send`` once at a time. ``write`` counts against the hourly budget."""
        with self._guard():
            wait = 0.0
            last_status = 503
            last_message = "GitHub API request failed."
            for attempt in range(self.max_retries + 1):
                if attempt > 0:
                    recovered = self._recover(before_retry, last_status, last_message)
                    if recovered is not None:
                        return recovered
                    if wait > 0:
                        self.sleep(wait)
                self._wait_out_block()
                if write:
                    self._pace_write()
                    self._ensure_budget()
                try:
                    result = send()
                except TransportError as exc:
                    if write:
                        self._record_write()
                    last_status = exc.status or 503
                    last_message = str(exc)
                    if attempt >= self.max_retries:
                        recovered = self._recover(before_retry, last_status, last_message)
                        if recovered is not None:
                            return recovered
                        raise RetryGaveUp(last_status, last_message) from None
                    wait = self.wait_seconds({}, attempt)
                    continue
                self._log_headers(result.status, result.headers)
                if write:
                    self._record_write()
                if result.status < 400 or not _retryable_status(result.status):
                    self._note_block(result.headers)
                    return result
                last_status = result.status
                last_message = result.body or f"GitHub API returned {result.status}."
                if attempt >= self.max_retries:
                    recovered = self._recover(before_retry, last_status, last_message)
                    if recovered is not None:
                        return recovered
                    raise RetryGaveUp(last_status, last_message)
                wait = self.wait_seconds(result.headers, attempt)
            raise RetryGaveUp(last_status, last_message)

    def wait_seconds(self, headers, attempt: int) -> float:
        now = float(self.clock())
        retry_after = retry_after_seconds(headers, now)
        if retry_after is not None:
            return min(self.max_wait, retry_after)
        remaining = _header_int(headers, "x-ratelimit-remaining")
        reset = _header_int(headers, "x-ratelimit-reset")
        if remaining == 0 and reset is not None:
            return min(self.max_wait, max(0.0, float(reset) - now))
        return min(self.max_wait, float(self.min_limit_wait * (2**attempt)))

    def _recover(self, before_retry, status: int, message: str) -> HttpResult | None:
        if before_retry is None:
            return None
        try:
            found = before_retry()
        except DoNotRetry:
            raise RetryGaveUp(status, message) from None
        if found is None:
            return None
        return HttpResult(200, {}, "", recovered=found)

    def _wait_out_block(self) -> None:
        delay = self._blocked_until - float(self.clock())
        if delay > 0:
            self.sleep(delay)
            self._blocked_until = float(self.clock())

    def _note_block(self, headers) -> None:
        remaining = _header_int(headers, "x-ratelimit-remaining")
        reset = _header_int(headers, "x-ratelimit-reset")
        if remaining == 0 and reset is not None:
            self._blocked_until = max(self._blocked_until, float(reset))

    def _log_headers(self, status: int, headers) -> None:
        remaining = _safe_field(header_value(headers, "x-ratelimit-remaining"), digits=True)
        limit = _safe_field(header_value(headers, "x-ratelimit-limit"), digits=True)
        reset = _safe_field(header_value(headers, "x-ratelimit-reset"), digits=True)
        resource = _safe_field(header_value(headers, "x-ratelimit-resource"), digits=False)
        if not any((remaining, limit, reset, resource)) and status not in (403, 429):
            return
        self.log(
            "GitHub rate limit: "
            f"status={status} remaining={remaining or '-'} limit={limit or '-'} "
            f"reset={reset or '-'} resource={resource or '-'}"
        )

    def _pace_write(self) -> None:
        if self.write_delay <= 0:
            return
        writes = self._load_writes()
        if not writes:
            return
        delay = max(writes) + self.write_delay - float(self.clock())
        if delay > 0:
            self.sleep(delay)

    def _ensure_budget(self) -> None:
        writes = self._load_writes()
        if len(writes) >= self.hourly_budget:
            oldest = min(writes)
            raise WriteBudgetExceeded(self.hourly_budget, len(writes), oldest + HOUR_SECONDS)

    def _record_write(self) -> None:
        writes = self._load_writes()
        writes.append(float(self.clock()))
        self._save_writes(writes)

    def _load_writes(self) -> list[float]:
        if self.state_path is None:
            source = list(self._memory_writes)
        else:
            source = self._read_file()
        cutoff = float(self.clock()) - HOUR_SECONDS
        return [item for item in source if item > cutoff]

    def _read_file(self) -> list[float]:
        assert self.state_path is not None
        if not self.state_path.exists():
            return []
        text = self.state_path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise SystemExit(
                f"{self.state_path} is not valid JSON. "
                "Leave it in place while a filing command is running."
            ) from None
        writes = data.get("writes") if isinstance(data, dict) else None
        if not isinstance(writes, list):
            raise SystemExit(f"{self.state_path} has no writes list.")
        parsed: list[float] = []
        for item in writes:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                continue
            parsed.append(float(item))
        return parsed

    def _save_writes(self, writes: list[float]) -> None:
        cutoff = float(self.clock()) - HOUR_SECONDS
        kept = [item for item in writes if item > cutoff]
        self._memory_writes = list(kept)
        if self.state_path is None:
            return
        payload = json.dumps({"version": 1, "writes": kept}, indent=2) + "\n"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, self.state_path)


def shared_limiter() -> Limiter:
    global _shared
    if _shared is None:
        _shared = Limiter.from_env()
    return _shared


def set_shared_limiter(limiter: Limiter) -> None:
    global _shared
    _shared = limiter


def run_github_cli(
    argv: list[str],
    *,
    write: bool,
    cwd: Path,
    env: dict[str, str] | None = None,
    limiter: Limiter | None = None,
    secrets: list[str] | None = None,
    runner=None,
    echo: bool = True,
) -> str:
    """Run a gh command through the limiter. Tokens are redacted from errors."""
    limiter = limiter or shared_limiter()
    runner = runner or subprocess.run
    secret_list = [value for value in (secrets or []) if value]
    secret_list.extend(_env_secrets(env))

    def send():
        completed = runner(
            argv,
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        stdout = redact(completed.stdout or "", secret_list)
        stderr = redact(completed.stderr or "", secret_list)
        try:
            return result_from_process(completed.returncode, stdout, stderr)
        except CommandFailed as exc:
            raise SystemExit(redact(str(exc), secret_list)[-500:]) from None

    try:
        result = limiter.execute(send, write=write)
    except WriteBudgetExceeded:
        raise
    except RetryGaveUp as exc:
        raise SystemExit(
            f"GitHub API returned {exc.status} after retries. "
            f"{redact(exc.message, secret_list)[-300:]}"
        ) from None
    if result.status >= 400:
        raise SystemExit(f"GitHub API returned {result.status}.")
    text = "" if result.recovered is not None else (result.body or "")
    if echo and text.strip():
        print(text, end="" if text.endswith("\n") else "\n")
    return text
