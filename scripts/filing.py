#!/usr/bin/env python3
"""File screened papers as GitHub issues and add them to a GitHub Project.

The run file (runs/<date>.json) is rewritten after each issue and each
project add. A later invocation reads that file and continues the pending
WP- ids. It does not start the queue over.

Before creating an issue, the command lists issue bodies and looks for
``<!-- wp-id: WP-0000 -->``. A 403, 429, 5xx, timeout, or dropped connection
is retried by ``gh_rate``. Before that retry sends another create, the same
marker lookup has to finish. A second create happens only when the marker
is still absent. Project adds follow the same rule.

Content-creating calls go through ``gh_rate.Limiter``: one at a time, at
least one second apart, and at most the hourly write budget (default 400).
When the budget is spent the run file is already saved and the command stops.

This module does not close, delete, or edit issues. It does not read or
write the retired spreadsheet. It does not print tokens.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import gh_rate
import inventory

DEFAULT_BATCH_SIZE = 25
LOOKUP_ATTEMPTS = 4
MAX_WRITES = 2
MAX_BODY = 65000
FINISHED = {"done", "already_filed"}
ACTIVE = {"pending", "issue_open"}
NETWORK_GUARD = "WHITEPAPER_FILING_DISABLE_NETWORK"

USER_PROJECT_QUERY = """
query($owner: String!, $number: Int!) {
  user(login: $owner) {
    projectV2(number: $number) { id }
  }
}
"""

ORG_PROJECT_QUERY = """
query($owner: String!, $number: Int!) {
  organization(login: $owner) {
    projectV2(number: $number) { id }
  }
}
"""

PROJECT_ITEMS_QUERY = """
query($id: ID!) {
  node(id: $id) {
    ... on Issue {
      projectItems(first: 50) {
        nodes { id project { id } }
      }
    }
  }
}
"""

ADD_PROJECT_ITEM = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {
    item { id }
  }
}
"""


class GithubError(Exception):
    """A GitHub response the caller may retry after a fresh lookup."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


class Match:
    def __init__(self, issue: dict, origin: str, extras: list[int] | None = None):
        self.issue = issue
        self.origin = origin
        self.extras = list(extras or [])


def redact(text: str, secrets: list[str]) -> str:
    cleaned = text or ""
    for secret in secrets:
        if secret and len(secret) >= 8:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def is_server_error(exc: BaseException) -> bool:
    return isinstance(exc, GithubError) and 500 <= exc.status <= 599


def backoff(attempt: int) -> float:
    return float(1 << attempt)


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def check_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise SystemExit(f"Date {value!r} is not YYYY-MM-DD.") from None
    return value


def resolve_batch_size(value: int | None) -> int:
    if value is None:
        raw = os.environ.get("WEEKLY_BATCH_SIZE", "").strip()
        if raw:
            if not raw.isdigit():
                raise SystemExit("WEEKLY_BATCH_SIZE must be a positive integer. Use 25 to 50.")
            value = int(raw)
        else:
            value = DEFAULT_BATCH_SIZE
    if value < 1:
        raise SystemExit("Batch size must be at least 1. Use 25 to 50 for a weekly run.")
    return value


def assert_not_raw(path: Path) -> None:
    """raw/ is read-only. Refuse a run file written there."""
    try:
        relative = path.resolve().relative_to(inventory.ROOT.resolve())
    except ValueError:
        relative = path
    if relative.parts and relative.parts[0] == "raw":
        raise SystemExit("raw/ is read-only.")


def roll_completed_run(path: Path, *, have_queue: bool, pinned: bool) -> Path:
    """Start a new dated file when the resumed run has no pending items and a new queue arrived."""
    if pinned or not have_queue or not path.exists():
        return path
    store = RunStore.load(path)
    if store.data["items"] and not store.data["pending"]:
        return path.parent / f"{utc_today()}.json"
    return path


def resolve_run_path(*, date: str = "", run: Path | None = None, root: Path | None = None) -> Path:
    root = root or inventory.ROOT
    runs = root / "runs"
    if run is not None:
        return Path(run)
    if date:
        check_date(date)
        return runs / f"{date}.json"
    pointer = runs / "latest.txt"
    if pointer.exists():
        pointed = pointer.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", pointed):
            return runs / f"{pointed}.json"
    return runs / f"{utc_today()}.json"


def note_latest(path: Path) -> None:
    if path.parent.name != "runs":
        return
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
        return
    pointer = path.parent / "latest.txt"
    assert_not_raw(pointer)
    pointer.write_text(path.stem + "\n", encoding="utf-8")


def remember(item: dict, step: str, **extra: object) -> None:
    history = item.setdefault("history", [])
    event = {"at": datetime.now(timezone.utc).isoformat(), "step": step}
    event.update(extra)
    history.append(event)
    del history[:-20]


class RunStore:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    @classmethod
    def load(cls, path: Path) -> "RunStore":
        assert_not_raw(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"{path} is not valid JSON.") from None
        if not isinstance(data, dict) or data.get("version") != 1:
            raise SystemExit(f"{path} is not a version 1 run file.")
        if not isinstance(data.get("items"), list):
            raise SystemExit(f"{path} has no items list.")
        store = cls(path, data)
        store.refresh_lists()
        return store

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        date: str,
        repository: str,
        project_owner: str,
        project_number: int,
        batch_size: int,
    ) -> "RunStore":
        assert_not_raw(path)
        data = {
            "version": 1,
            "date": date,
            "repository": repository,
            "project_owner": project_owner,
            "project_number": project_number,
            "project_id": "",
            "batch_size": batch_size,
            "updated": "",
            "done": [],
            "pending": [],
            "issues": {},
            "created_issues": {},
            "items": [],
        }
        store = cls(path, data)
        store.save()
        return store

    def items(self) -> list[dict]:
        return self.data["items"]

    def refresh_lists(self) -> None:
        done = []
        pending = []
        issues = {}
        created = {}
        for item in self.items():
            wp_id = item.get("wp_id")
            if not isinstance(wp_id, str):
                continue
            if item.get("status") in FINISHED:
                done.append(wp_id)
            else:
                pending.append(wp_id)
            number = item.get("issue_number")
            if isinstance(number, int):
                issues[wp_id] = number
                if item.get("created"):
                    created[wp_id] = number
        self.data["done"] = done
        self.data["pending"] = pending
        self.data["issues"] = issues
        self.data["created_issues"] = created

    def save(self) -> None:
        assert_not_raw(self.path)
        self.refresh_lists()
        self.data["updated"] = datetime.now(timezone.utc).isoformat()
        text = json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / (self.path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, self.path)
        note_latest(self.path)


def prepare_run(
    path: Path,
    *,
    date: str,
    repository: str,
    project_owner: str,
    project_number: int,
    batch_size: int,
) -> RunStore:
    if path.exists():
        store = RunStore.load(path)
        recorded = store.data.get("repository") or ""
        if recorded and recorded != repository:
            raise SystemExit(f"{path} is for {recorded}, not {repository}.")
        store.data["repository"] = repository
        store.data["batch_size"] = batch_size
        store.data["project_owner"] = project_owner
        store.data["project_number"] = project_number
        store.save()
        return store
    return RunStore.create(
        path,
        date=date,
        repository=repository,
        project_owner=project_owner,
        project_number=project_number,
        batch_size=batch_size,
    )


def normalize_queue_item(raw: object, index: int) -> dict:
    if not isinstance(raw, dict):
        raise SystemExit(f"Queue item {index} is not an object.")
    title = str(raw.get("title") or "").strip()
    source = str(raw.get("source") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not title or "\n" in title or "\r" in title:
        raise SystemExit(f"Queue item {index} needs a one-line title.")
    if not source or "\n" in source or "\r" in source:
        raise SystemExit(f"Queue item {index} needs a one-line source.")
    if not url.lower().startswith(("http://", "https://")):
        raise SystemExit(f"Queue item {index} needs an http(s) URL.")
    wp_id = str(raw.get("wp_id") or "").strip()
    if wp_id and not inventory.WP_ID_RE.fullmatch(wp_id):
        raise SystemExit(f"Queue item {index} has wp_id {wp_id!r}.")
    return {
        "title": title,
        "source": source,
        "url": url,
        "url_key": inventory.normalize_url(url),
        "date_published": str(raw.get("date_published") or "").strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "body": str(raw.get("body") or ""),
        "wp_id": wp_id,
        "arxiv_id": str(raw.get("arxiv_id") or "").strip(),
        "cited_by": str(raw.get("cited_by") or "").strip(),
        "evidence_level": str(raw.get("evidence_level") or "").strip(),
    }


def load_queue(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise SystemExit(f"Could not read {path}.") from None
    except json.JSONDecodeError:
        raise SystemExit(f"{path} is not valid JSON.") from None
    if isinstance(data, dict):
        items = data.get("items")
    elif isinstance(data, list):
        items = data
    else:
        items = None
    if not isinstance(items, list):
        raise SystemExit(f"{path} needs a list of papers, or an object with an items list.")
    normalized = [normalize_queue_item(item, index) for index, item in enumerate(items, start=1)]
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    for item in normalized:
        if item["url_key"] in seen_urls:
            raise SystemExit(f"Queue lists {item['url']} more than once.")
        seen_urls.add(item["url_key"])
        if item["wp_id"]:
            if item["wp_id"] in seen_ids:
                raise SystemExit(f"Queue lists {item['wp_id']} more than once.")
            seen_ids.add(item["wp_id"])
    return normalized


def registry_maps(document: dict | None) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """Map a normalized URL to every registry entry for that URL."""
    by_url: dict[str, list[dict]] = {}
    by_id: dict[str, dict] = {}
    if not document:
        return by_url, by_id
    for entry in document.get("id_registry") or []:
        if not isinstance(entry, dict):
            continue
        wp_id = entry.get("wp_id")
        url = entry.get("url")
        if isinstance(wp_id, str) and isinstance(url, str):
            by_id[wp_id] = entry
            by_url.setdefault(url, []).append(entry)
    return by_url, by_id


def new_item(raw: dict, wp_id: str, *, status: str, issue_number: int | None) -> dict:
    item = {
        "wp_id": wp_id,
        "title": raw["title"],
        "source": raw["source"],
        "url": raw["url"],
        "url_key": raw["url_key"],
        "date_published": raw["date_published"],
        "summary": raw["summary"],
        "body": raw["body"],
        "arxiv_id": raw["arxiv_id"],
        "cited_by": raw["cited_by"],
        "evidence_level": raw["evidence_level"],
        "status": status,
        "issue_number": issue_number,
        "issue_node_id": "",
        "project_item_id": "",
        "created": False,
        "also_found": [],
        "history": [],
    }
    remember(item, status, issue_number=issue_number)
    return item


def merge_queue(store: RunStore, queue: list[dict], document: dict | None) -> int:
    """Reserve WP- ids and append new papers. Existing URLs are left as they are."""
    by_url, by_id = registry_maps(document)
    used = set(by_id)
    for item in store.items():
        used.add(item["wp_id"])
    run_urls = {item["url_key"]: item for item in store.items()}
    run_ids = {item["wp_id"] for item in store.items()}
    added = 0
    for raw in queue:
        if raw["url_key"] in run_urls:
            existing = run_urls[raw["url_key"]]
            if raw["wp_id"] and raw["wp_id"] != existing["wp_id"]:
                raise SystemExit(
                    f"{raw['url']} is already in this run as {existing['wp_id']}."
                )
            continue
        if raw["wp_id"] and raw["wp_id"] in run_ids:
            raise SystemExit(f"{raw['wp_id']} is already in this run for a different URL.")
        reserved_list = sorted(
            by_url.get(raw["url_key"]) or [],
            key=lambda entry: int(entry["issue_number"]),
        )
        if reserved_list:
            chosen = reserved_list[0]
            if raw["wp_id"]:
                match = [entry for entry in reserved_list if entry.get("wp_id") == raw["wp_id"]]
                if not match:
                    names = ", ".join(str(entry.get("wp_id")) for entry in reserved_list)
                    raise SystemExit(f"{raw['url']} already has {names}.")
                chosen = match[0]
            wp_id = str(chosen["wp_id"])
            store.items().append(
                new_item(raw, wp_id, status="already_filed", issue_number=int(chosen["issue_number"]))
            )
        else:
            if raw["wp_id"]:
                if raw["wp_id"] in used:
                    owner = by_id.get(raw["wp_id"])
                    if owner:
                        raise SystemExit(f"{raw['wp_id']} is reserved for {owner['url']}.")
                    raise SystemExit(f"{raw['wp_id']} is already in this run.")
                wp_id = raw["wp_id"]
                used.add(wp_id)
            else:
                wp_id = inventory._allocate(used)
            store.items().append(new_item(raw, wp_id, status="pending", issue_number=None))
        current = store.items()[-1]
        run_urls[raw["url_key"]] = current
        run_ids.add(current["wp_id"])
        added += 1
    if added:
        store.save()
    return added


def _has_heading(text: str, title: str) -> bool:
    return re.search(rf"(?m)^### {re.escape(title)}\s*$", text) is not None


def ensure_extraction_sections(text: str) -> str:
    """Add any missing extraction heading. An old Invariables heading counts."""
    required = (
        ("Axioms", ()),
        ("Invariants", ("Invariables",)),
        ("Principles", ()),
        ("OpenCRE Topics", ()),
    )
    missing = []
    for title, aliases in required:
        if _has_heading(text, title) or any(_has_heading(text, alias) for alias in aliases):
            continue
        missing.append(title)
    if not missing:
        return text if text.endswith("\n") else text + "\n"
    if not text.endswith("\n"):
        text += "\n"
    if not text.endswith("\n\n"):
        text += "\n"
    blocks = [f"### {title}\n_Not filled yet._\n" for title in missing]
    return text + "\n".join(blocks)


def render_issue_body(item: dict) -> str:
    wp_id = item["wp_id"]
    marker = inventory.wp_id_marker(wp_id)
    custom = str(item.get("body") or "").strip()
    if custom:
        found = inventory.marker_wp_ids(custom)
        if any(value != wp_id for value in found):
            raise SystemExit(f"{wp_id} queue body is marked with a different id.")
        if found:
            text = custom if custom.endswith("\n") else custom + "\n"
        else:
            text = f"{marker}\n\n{custom}\n"
    else:
        lines = [marker, "", f"**Source:** {item['source']}", f"**Link:** {item['url']}"]
        if item.get("date_published"):
            lines.append(f"**Date published:** {item['date_published']}")
        lines.append("")
        if item.get("summary"):
            lines.append(item["summary"])
            lines.append("")
        lines.extend(
            [
                "### Axioms",
                "_Not filled yet._",
                "",
                "### Invariants",
                "_Not filled yet._",
                "",
                "### Principles",
                "_Not filled yet._",
                "",
                "### OpenCRE Topics",
                "_Not filled yet._",
                "",
            ]
        )
        if item.get("arxiv_id"):
            lines.append("### arXiv reference")
            lines.append(f"- arXiv ID: {item['arxiv_id']}")
            if item.get("cited_by"):
                lines.append(f"- Cited by monitored papers: {item['cited_by']}")
            if item.get("evidence_level"):
                lines.append(f"- Evidence level: {item['evidence_level']}")
            lines.append("")
        elif item.get("evidence_level"):
            lines.extend(
                [
                    "### Evidence",
                    f"- Evidence level: {item['evidence_level']}",
                    "",
                ]
            )
        text = "\n".join(lines)
        if not text.endswith("\n"):
            text += "\n"
    text = ensure_extraction_sections(text)
    if len(text) > MAX_BODY:
        raise SystemExit(f"{wp_id} body is longer than {MAX_BODY} characters.")
    return text


def issue_url_key(body: str) -> str:
    for line in (body or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("**link:**"):
            found = inventory.URL_RE.search(stripped)
            if found:
                return inventory.normalize_url(found.group(0))
    sheet = inventory.SHEET_URL_RE.search(body or "")
    if sheet:
        found = inventory.URL_RE.search(sheet.group(1))
        if found:
            return inventory.normalize_url(found.group(0))
    return ""


def classify(issues: list[dict], wp_id: str, url: str) -> Match | None:
    url_key = inventory.normalize_url(url)
    marked = []
    linked = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        body = issue.get("body") or ""
        if wp_id in inventory.marker_wp_ids(body):
            marked.append(issue)
            continue
        if issue_url_key(body) == url_key:
            linked.append(issue)
    if marked:
        marked.sort(key=_issue_rank)
        extras = [int(item["number"]) for item in marked[1:]]
        return Match(marked[0], "marker", extras)
    if linked:
        linked.sort(key=_issue_rank)
        extras = [int(item["number"]) for item in linked[1:]]
        return Match(linked[0], "url", extras)
    return None


def _issue_rank(issue: dict) -> tuple:
    """Same order build_papers uses to choose the issue that keeps the WP- id."""
    body = issue.get("body") or ""
    removed = 1 if inventory.REMOVED_DUP_RE.search(body) else 0
    state = 0 if str(issue.get("state") or "").lower() == "open" else 1
    sheet = 0 if inventory.SHEET_URL_RE.search(body) else 1
    return (removed, state, sheet, int(issue["number"]))


def lookup_existing(client, item: dict, sleep) -> Match | None:
    """List issues until a check completes. A failed list is not treated as absence."""
    last: GithubError | None = None
    for attempt in range(LOOKUP_ATTEMPTS):
        try:
            issues = client.list_issues()
        except GithubError as exc:
            if not is_server_error(exc):
                raise
            last = exc
            if attempt + 1 < LOOKUP_ATTEMPTS:
                sleep(backoff(attempt))
            continue
        if not isinstance(issues, list):
            raise SystemExit("GitHub API returned an unexpected issues payload.")
        return classify(issues, item["wp_id"], item["url"])
    assert last is not None
    raise last


def fetch_known(client, number: int, sleep) -> dict | None:
    last: GithubError | None = None
    for attempt in range(LOOKUP_ATTEMPTS):
        try:
            return client.get_issue(number)
        except GithubError as exc:
            if exc.status == 404:
                return None
            if not is_server_error(exc):
                raise
            last = exc
            if attempt + 1 < LOOKUP_ATTEMPTS:
                sleep(backoff(attempt))
            continue
    assert last is not None
    raise last


def ensure_issue(client, item: dict, *, sleep) -> Match:
    """Return the issue for this WP- id. Create only after a completed lookup misses it."""
    number = item.get("issue_number")
    if isinstance(number, int):
        known = fetch_known(client, number, sleep)
        if known is not None:
            body = known.get("body") or ""
            if item["wp_id"] in inventory.marker_wp_ids(body):
                return Match(known, "marker", [])
            if issue_url_key(body) == inventory.normalize_url(item["url"]):
                return Match(known, "url", [])
            if item.get("created"):
                return Match(known, "marker", [])
    creates = 0
    while creates < MAX_WRITES:
        match = lookup_existing(client, item, sleep)
        if match:
            return match
        try:
            creates += 1
            issue = client.create_issue(item["title"], render_issue_body(item))
        except GithubError as exc:
            if not is_server_error(exc):
                raise
            match = lookup_existing(client, item, sleep)
            if match:
                return match
            continue
        if not isinstance(issue, dict) or "number" not in issue:
            raise SystemExit(f"{item['wp_id']} was created but GitHub returned no issue number.")
        return Match(issue, "created", [])
    match = lookup_existing(client, item, sleep)
    if match:
        return match
    raise GithubError(502, f"Could not file {item['wp_id']} after a GitHub server error.")


def lookup_project_item(client, node_id: str, project_id: str, sleep) -> str:
    last: GithubError | None = None
    for attempt in range(LOOKUP_ATTEMPTS):
        try:
            found = client.project_item_id(node_id, project_id)
        except GithubError as exc:
            if not is_server_error(exc):
                raise
            last = exc
            if attempt + 1 < LOOKUP_ATTEMPTS:
                sleep(backoff(attempt))
            continue
        return found or ""
    assert last is not None
    raise last


def ensure_project_item(client, project_id: str, node_id: str, *, sleep) -> str:
    """Add the issue to the project. A 5xx is followed by a lookup before another add."""
    if not node_id:
        raise SystemExit("The issue has no node id, so it cannot be added to the project.")
    adds = 0
    while adds < MAX_WRITES:
        found = lookup_project_item(client, node_id, project_id, sleep)
        if found:
            return found
        try:
            adds += 1
            item_id = client.add_project_item(project_id, node_id)
        except GithubError as exc:
            if not is_server_error(exc):
                raise
            found = lookup_project_item(client, node_id, project_id, sleep)
            if found:
                return found
            continue
        if not item_id:
            raise SystemExit("GitHub project API did not return an item id.")
        return str(item_id)
    found = lookup_project_item(client, node_id, project_id, sleep)
    if found:
        return found
    raise GithubError(502, "Could not add the project item after a GitHub server error.")


def file_item(store: RunStore, client, project_id: str, item: dict, *, sleep, skip_project: bool) -> None:
    status = item.get("status")
    if status not in FINISHED | ACTIVE:
        raise SystemExit(f"{item.get('wp_id')} has status {status!r}.")
    if status in FINISHED:
        return
    if status == "pending":
        match = ensure_issue(client, item, sleep=sleep)
        issue = match.issue
        item["issue_number"] = int(issue["number"])
        item["issue_node_id"] = str(issue.get("node_id") or "")
        if match.extras:
            item["also_found"] = list(match.extras)
        if match.origin == "url":
            item["created"] = False
            item["status"] = "already_filed"
            remember(item, "already_filed", issue_number=item["issue_number"])
            store.save()
            return
        item["created"] = True
        item["status"] = "issue_open"
        remember(item, "issue_open", issue_number=item["issue_number"])
        store.save()
    if item.get("status") != "issue_open":
        return
    if skip_project or not project_id:
        return
    if not item.get("issue_node_id"):
        match = ensure_issue(client, item, sleep=sleep)
        item["issue_number"] = int(match.issue["number"])
        item["issue_node_id"] = str(match.issue.get("node_id") or "")
        if match.origin == "url" and not item.get("created"):
            item["created"] = False
            item["status"] = "already_filed"
            remember(item, "already_filed", issue_number=item["issue_number"])
            store.save()
            return
        store.save()
    item["project_item_id"] = ensure_project_item(
        client,
        project_id,
        item["issue_node_id"],
        sleep=sleep,
    )
    item["status"] = "done"
    remember(item, "done", issue_number=item["issue_number"], project_item_id=item["project_item_id"])
    store.save()


def next_batch(items: list[dict], batch_size: int) -> list[dict]:
    opened = [item for item in items if item.get("status") == "issue_open"]
    pending = [item for item in items if item.get("status") == "pending"]
    return (opened + pending)[:batch_size]


def file_batch(
    store: RunStore,
    client,
    project_id: str,
    batch_size: int,
    *,
    sleep=time.sleep,
    skip_project: bool = False,
    on_item=None,
) -> int:
    chosen = next_batch(store.items(), batch_size)
    filed = 0
    try:
        for item in chosen:
            file_item(store, client, project_id, item, sleep=sleep, skip_project=skip_project)
            filed += 1
            if on_item:
                on_item(item)
    except gh_rate.WriteBudgetExceeded:
        store.save()
        raise
    return filed


def format_run(store: RunStore) -> str:
    store.refresh_lists()
    data = store.data
    lines = [
        f"Run {data.get('date')}: {len(data['done'])} done, {len(data['pending'])} pending.",
    ]
    created = data.get("created_issues") or {}
    if created:
        lines.append("Created issues:")
        for wp_id, number in created.items():
            lines.append(f"  {wp_id} issue #{number}")
    if data["pending"]:
        lines.append("Pending:")
        for wp_id in data["pending"]:
            lines.append(f"  {wp_id}")
    return "\n".join(lines)


class GithubRestClient:
    """Issue and project calls. Tokens stay in headers or in the gh login."""

    def __init__(
        self,
        repo: str,
        issue_token: str = "",
        project_token: str = "",
        opener=None,
        runner=None,
        limiter: gh_rate.Limiter | None = None,
    ):
        self.repo = repo
        self.issue_token = issue_token or ""
        self.project_token = project_token or issue_token or ""
        self.opener = opener or urllib.request.urlopen
        self.runner = runner or subprocess.run
        self.limiter = limiter
        self.secrets = [value for value in (self.issue_token, self.project_token) if value]

    def _limiter(self) -> gh_rate.Limiter:
        if self.limiter is None:
            self.limiter = gh_rate.shared_limiter()
        return self.limiter

    def redact(self, text: str) -> str:
        return redact(text, self.secrets)

    def _guard(self) -> None:
        if os.environ.get(NETWORK_GUARD) == "1":
            raise SystemExit("Network is disabled for this process.")

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "whitepaper-inventory",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _raise_http(self, status: int, raw: str) -> None:
        message = self.redact(raw).replace("\n", " ")[:500]
        if status == 404:
            raise GithubError(404, "GitHub API returned 404.")
        if status in (403, 429) or 500 <= status <= 599:
            raise GithubError(status, f"GitHub API returned {status}. {message}")
        raise SystemExit(f"GitHub API returned {status}. {message}")

    def _json(self, raw: str):
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raise SystemExit("GitHub API returned data that is not JSON.") from None

    def _call(self, send, *, write: bool, before_retry=None) -> gh_rate.HttpResult:
        try:
            result = self._limiter().execute(send, write=write, before_retry=before_retry)
        except gh_rate.WriteBudgetExceeded:
            raise
        except gh_rate.RetryGaveUp as exc:
            self._raise_http(exc.status or 504, exc.message)
        if result.recovered is not None:
            return result
        if result.status >= 400:
            self._raise_http(result.status, result.body)
        return result

    def _urllib_send(self, method: str, url: str, payload: dict | None, token: str, retry_on_body=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=self._headers(token), method=method)

        def send():
            result = gh_rate.perform_urllib(self.opener, request, timeout=60)
            if retry_on_body is not None and result.status < 400 and retry_on_body(result.body):
                return gh_rate.HttpResult(429, result.headers, result.body)
            return result

        return send

    def _gh_send(self, method: str, path: str, payload: dict | None, retry_on_body=None):
        command = ["gh", "api", "--include", "--method", method, path]
        stdin = None
        if payload is not None:
            command.extend(["--input", "-"])
            stdin = json.dumps(payload)

        def send():
            try:
                completed = self.runner(
                    command,
                    input=stdin,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except FileNotFoundError:
                raise SystemExit("Install the gh CLI, or set GITHUB_TOKEN.") from None
            stdout = self.redact(completed.stdout or "")
            stderr = self.redact(completed.stderr or "")
            try:
                result = gh_rate.result_from_process(completed.returncode, stdout, stderr)
            except gh_rate.CommandFailed as exc:
                raise SystemExit(f"GitHub API request failed. {self.redact(str(exc))[-300:]}") from None
            if retry_on_body is not None and result.status < 400 and retry_on_body(result.body):
                return gh_rate.HttpResult(429, result.headers, result.body)
            return result

        return send

    def _extend_issues(self, found: list[dict], result: gh_rate.HttpResult) -> str:
        batch = self._json(result.body)
        if not isinstance(batch, list):
            raise SystemExit(f"GitHub API returned an unexpected issues payload for {self.repo}.")
        found.extend(item for item in batch if "pull_request" not in item)
        return inventory._next_url(gh_rate.header_value(result.headers, "link"))

    def list_issues(self) -> list[dict]:
        self._guard()
        found: list[dict] = []
        if not self.issue_token:
            path = f"repos/{self.repo}/issues?state=all&per_page=100"
            while path:
                current = path
                result = self._call(self._gh_send("GET", current, None), write=False)
                path = self._extend_issues(found, result)
            return found
        url = f"https://api.github.com/repos/{self.repo}/issues?state=all&per_page=100"
        while url:
            current = url
            result = self._call(self._urllib_send("GET", current, None, self.issue_token), write=False)
            url = self._extend_issues(found, result)
        return found

    def get_issue(self, number: int) -> dict:
        self._guard()
        if not self.issue_token:
            result = self._call(self._gh_send("GET", f"repos/{self.repo}/issues/{int(number)}", None), write=False)
        else:
            result = self._call(
                self._urllib_send(
                    "GET",
                    f"https://api.github.com/repos/{self.repo}/issues/{int(number)}",
                    None,
                    self.issue_token,
                ),
                write=False,
            )
        issue = self._json(result.body)
        if not isinstance(issue, dict):
            raise SystemExit(f"GitHub API returned an unexpected payload for issue {number}.")
        return issue

    def _issue_exists(self, body: str):
        """Look up the wp-id marker before a create is sent again."""

        def before_retry():
            wp_ids = inventory.marker_wp_ids(body)
            if not wp_ids:
                raise gh_rate.DoNotRetry()
            url = issue_url_key(body)
            try:
                issues = self.list_issues()
            except GithubError:
                raise gh_rate.DoNotRetry()
            for wp_id in wp_ids:
                match = classify(issues, wp_id, url)
                if match is not None:
                    return match.issue
            return None

        return before_retry

    def create_issue(self, title: str, body: str) -> dict:
        self._guard()
        payload = {"title": title, "body": body}
        before_retry = self._issue_exists(body)
        if not self.issue_token:
            result = self._call(
                self._gh_send("POST", f"repos/{self.repo}/issues", payload),
                write=True,
                before_retry=before_retry,
            )
        else:
            result = self._call(
                self._urllib_send(
                    "POST",
                    f"https://api.github.com/repos/{self.repo}/issues",
                    payload,
                    self.issue_token,
                ),
                write=True,
                before_retry=before_retry,
            )
        if result.recovered is not None:
            issue = result.recovered
        else:
            issue = self._json(result.body)
        if not isinstance(issue, dict) or "number" not in issue:
            raise SystemExit("GitHub API did not return an issue number.")
        return issue

    def _graphql_limited(self, body: str) -> bool:
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed, dict):
            return False
        for error in parsed.get("errors") or []:
            if not isinstance(error, dict):
                continue
            if str(error.get("type") or "").upper() == "RATE_LIMITED":
                return True
            if "rate limit" in str(error.get("message") or "").lower():
                return True
        return False

    def _graphql_result(self, query: str, variables: dict, before_retry=None) -> gh_rate.HttpResult:
        self._guard()
        payload = {"query": query, "variables": variables}
        token = self.project_token or self.issue_token
        write = query.lstrip().lower().startswith("mutation")
        if not token:
            send = self._gh_send("POST", "graphql", payload, retry_on_body=self._graphql_limited)
        else:
            send = self._urllib_send(
                "POST",
                "https://api.github.com/graphql",
                payload,
                token,
                retry_on_body=self._graphql_limited,
            )
        return self._call(send, write=write, before_retry=before_retry)

    def _graphql_data(self, result: gh_rate.HttpResult) -> dict:
        parsed = self._json(result.body)
        if not isinstance(parsed, dict):
            raise SystemExit("GitHub project API returned an unexpected payload.")
        errors = parsed.get("errors") or []
        if errors:
            message = "; ".join(str(error.get("message") or "") for error in errors if isinstance(error, dict))
            message = self.redact(message)
            lowered = message.lower()
            if any(word in lowered for word in ("timeout", "something went wrong", "server error", "502", "503", "504")):
                raise GithubError(502, message or "GitHub project API returned a server error.")
            raise SystemExit(f"GitHub project API: {message}")
        data = parsed.get("data")
        if not isinstance(data, dict):
            raise SystemExit("GitHub project API returned no data.")
        return data

    def graphql(self, query: str, variables: dict) -> dict:
        result = self._graphql_result(query, variables)
        return self._graphql_data(result)

    def project_item_id(self, node_id: str, project_id: str) -> str:
        data = self.graphql(PROJECT_ITEMS_QUERY, {"id": node_id})
        node = data.get("node") or {}
        items = ((node.get("projectItems") or {}).get("nodes")) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            project = item.get("project") or {}
            if project.get("id") == project_id and item.get("id"):
                return str(item["id"])
        return ""

    def add_project_item(self, project_id: str, node_id: str) -> str:
        def before_retry():
            try:
                found = self.project_item_id(node_id, project_id)
            except GithubError:
                raise gh_rate.DoNotRetry()
            return found or None

        result = self._graphql_result(
            ADD_PROJECT_ITEM,
            {"project": project_id, "content": node_id},
            before_retry=before_retry,
        )
        if result.recovered:
            return str(result.recovered)
        data = self._graphql_data(result)
        item = (data.get("addProjectV2ItemById") or {}).get("item") or {}
        item_id = item.get("id") or ""
        if not item_id:
            raise SystemExit("GitHub project API did not return an item id.")
        return str(item_id)


def resolve_project_id(client, owner: str, number: int) -> str:
    queries = (("user", USER_PROJECT_QUERY), ("organization", ORG_PROJECT_QUERY))
    for key, query in queries:
        try:
            data = client.graphql(query, {"owner": owner, "number": number})
        except SystemExit as exc:
            if "Could not resolve" in str(exc):
                continue
            raise
        node = data.get(key) or {}
        project = node.get("projectV2") or {}
        if project.get("id"):
            return str(project["id"])
    raise SystemExit(
        f"No GitHub Project {number} for {owner}. The weekly pass adds new issues to project 2."
    )


def issue_token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


def project_token() -> str:
    return os.environ.get("GITHUB_PROJECTS_TOKEN") or issue_token()


def secrets_from_env() -> list[str]:
    values = [
        os.environ.get("GITHUB_TOKEN", ""),
        os.environ.get("GH_TOKEN", ""),
        os.environ.get("GITHUB_PROJECTS_TOKEN", ""),
    ]
    return [value for value in values if value]
