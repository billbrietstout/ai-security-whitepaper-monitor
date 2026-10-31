#!/usr/bin/env python3
"""Read GitHub issues and build the whitepaper inventory.

The issues in this repo are the source of truth. This module does not read
or write the retired Google Sheet. A hidden ``<!-- sheet-url: ... -->`` line
is kept as legacy provenance when an issue still has one. New issues do not
need that line.

Each paper keeps the WP- id already stored in ``data/whitepapers.json``.
The id stays on that issue and that normalized URL. A new URL receives the
next free id. An issue whose URL already has an id does not receive a second
one, unless that issue already has its own id in the registry. Six URLs were
filed twice before the sheet was retired, and both copies kept the ids they
already had.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "data" / "whitepapers.json"
CSV_PATH = ROOT / "data" / "whitepapers.csv"

SCHEMA_VERSION = 1
SOURCE = "github-issues"
RETIRED_SHEET_ID = "161FFOVjQUNxiaOzMryT6sbEuYjq-uLf-vcDEHfvlFbE"
RETIRED_ON = "2026-10-31"
SYNC_FOOTER = "_Synced from the whitepaper sheet. Edit the sheet, not this issue._"

BULLET_SECTIONS = {
    "Axioms": "axioms",
    "Invariables": "invariables",
    "Principles": "principles",
    "OpenCRE Topics": "opencre_topics",
}
CARRIED_SKIP = {"Date published", "Category", "File type", "Sheet tab and row"}
DECISIONS = {
    "include": "include",
    "delete candidate": "delete_candidate",
    "duplicate": "duplicate",
}

SHEET_URL_RE = re.compile(r"<!--\s*sheet-url:\s*(.*?)\s*-->", re.DOTALL)
REMOVED_DUP_RE = re.compile(r"<!--\s*removed-duplicate-marker\s*-->")
FIELD_RE = re.compile(r"^\*\*([^*]+):\*\*\s*(.*)$")
CARRIED_RE = re.compile(r"^-\s+\*\*([^*]+):\*\*\s*(.*)$")
URL_RE = re.compile(r"https?://[^\s)>]+")
WP_ID_RE = re.compile(r"^WP-[0-9]{4}$")


def normalize_url(url: str) -> str:
    """Key used to keep a WP- id on one paper across exports."""
    raw = url.strip()
    found = URL_RE.search(raw)
    if found:
        raw = found.group(0)
    parts = urlsplit(raw.strip())
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query) if not key.lower().startswith("utm_")]
    )
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    return urlunsplit((scheme, parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def repository_slug() -> str:
    """Return owner/repo. Never include a credential from the git remote."""
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", env):
        return env
    try:
        remote = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        remote = ""
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    if not match:
        raise SystemExit("Set GITHUB_REPOSITORY to owner/repo.")
    return f"{match.group(1)}/{match.group(2)}"


def _next_url(link_header: str) -> str:
    for part in link_header.split(","):
        if 'rel="next"' not in part:
            continue
        start = part.find("<")
        end = part.find(">")
        if start != -1 and end != -1:
            return part[start + 1 : end]
    return ""


def _fetch_with_token(repo: str, token: str) -> list[dict]:
    url = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100"
    found: list[dict] = []
    while url:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "whitepaper-inventory",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                batch = json.loads(response.read().decode())
                link_header = response.headers.get("Link", "")
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"GitHub API returned {exc.code} while listing issues in {repo}.") from None
        if not isinstance(batch, list):
            raise SystemExit(f"GitHub API returned an unexpected issues payload for {repo}.")
        found.extend(item for item in batch if "pull_request" not in item)
        url = _next_url(link_header)
    return found


def _fetch_with_gh(repo: str) -> list[dict]:
    try:
        raw = subprocess.check_output(
            ["gh", "api", "--paginate", f"repos/{repo}/issues?state=all&per_page=100"],
            text=True,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise SystemExit("Set GITHUB_TOKEN or GH_TOKEN, or install the gh CLI.") from None
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else "gh api failed"
        raise SystemExit(f"Could not list issues in {repo}: {tail}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(f"GitHub API returned data that is not JSON for {repo}.") from None
    if not isinstance(data, list):
        raise SystemExit(f"GitHub API returned an unexpected issues payload for {repo}.")
    return [item for item in data if "pull_request" not in item]


def fetch_issues(repo: str | None = None) -> list[dict]:
    """List every issue. The token stays in the request header or in gh."""
    repo = repo or repository_slug()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return _fetch_with_token(repo, token)
    return _fetch_with_gh(repo)


def _section_map(body: str) -> tuple[str, dict[str, str]]:
    parts = re.split(r"(?m)^### ", body)
    sections: dict[str, str] = {}
    for part in parts[1:]:
        lines = part.splitlines()
        title = lines[0].strip()
        sections[title] = "\n".join(lines[1:])
    return parts[0], sections


def _clean_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        if line.strip() == SYNC_FOOTER:
            continue
        lines.append(line)
    return lines


def _bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in _clean_lines(text):
        stripped = line.strip()
        if not stripped or stripped == "_Not filled yet._":
            continue
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif stripped.startswith("-"):
            item = stripped[1:].strip()
            if item:
                items.append(item)
        elif items:
            items[-1] = f"{items[-1]} {stripped}"
        else:
            items.append(stripped)
    return [item for item in items if item]


def _first_url(text: str) -> str:
    for line in _clean_lines(text):
        stripped = line.strip()
        if not stripped or stripped == "_Not filled yet._":
            continue
        found = URL_RE.search(stripped)
        if found:
            return found.group(0)
        return stripped
    return ""


def parse_issue(issue: dict) -> dict:
    """Turn one GitHub issue into fields. Does not assign a WP- id."""
    number = int(issue["number"])
    body = issue.get("body") or ""
    if not body.strip():
        raise SystemExit(f"Issue {number} has an empty body.")
    sheet_match = SHEET_URL_RE.search(body)
    legacy_sheet_url = ""
    if sheet_match:
        found = URL_RE.search(sheet_match.group(1))
        legacy_sheet_url = found.group(0) if found else sheet_match.group(1).strip()
    preamble, sections = _section_map(body)
    clean = re.sub(r"<!--.*?-->", "", preamble, flags=re.DOTALL)
    fields: dict[str, str] = {}
    summary_lines: list[str] = []
    for line in clean.splitlines():
        stripped = line.strip()
        field = FIELD_RE.match(stripped)
        if field:
            fields[field.group(1).strip()] = field.group(2).strip()
            continue
        if not stripped or stripped == SYNC_FOOTER:
            continue
        if re.match(r"^Duplicate of #\d+", stripped):
            continue
        summary_lines.append(stripped)

    link = fields.get("Link", "")
    url = ""
    if link:
        found = URL_RE.search(link)
        url = found.group(0) if found else link.strip()
    if not url:
        raise SystemExit(f"Issue {number} has no Link line.")
    source = fields.get("Source", "").strip()
    if not source:
        raise SystemExit(f"Issue {number} has no Source line.")

    carried: dict[str, str] = {}
    unknown_sections: list[str] = []
    bullets = {name: [] for name in BULLET_SECTIONS.values()}
    blog_url = ""
    for title, text in sections.items():
        if title in BULLET_SECTIONS:
            bullets[BULLET_SECTIONS[title]] = _bullets(text)
        elif title == "Blog / Announcement":
            blog_url = _first_url(text)
        elif title.startswith("Carried over"):
            for line in text.splitlines():
                match = CARRIED_RE.match(line.strip())
                if match:
                    carried[match.group(1).strip()] = match.group(2).strip()
        else:
            extra = "\n".join(line.strip() for line in _clean_lines(text) if line.strip())
            if extra:
                unknown_sections.append(f"{title}\n{extra}")

    extra_notes = [
        f"{name}: {value}" for name, value in carried.items() if name not in CARRIED_SKIP and value
    ]
    legacy_notes = "\n".join(extra_notes + unknown_sections)
    date_published = carried.get("Date published") or fields.get("Date published") or ""
    state = str(issue.get("state") or "").lower()
    if state not in ("open", "closed"):
        raise SystemExit(f"Issue {number} has an unexpected state.")
    removed_duplicate = bool(REMOVED_DUP_RE.search(body))
    label = fields.get("Decision", "").strip().lower()
    raw_decision = fields.get("Decision", "").strip()
    if label == "" and state == "open":
        decision = "include"
    elif label == "" and removed_duplicate:
        # Interrupted sync runs closed a second copy and did not set Decision.
        decision = "duplicate"
    elif label not in DECISIONS:
        raise SystemExit(f"Issue {number} has Decision {raw_decision!r}.")
    elif state == "open" and DECISIONS[label] != "include":
        raise SystemExit(f"Issue {number} is open and has Decision {raw_decision!r}.")
    else:
        decision = DECISIONS[label]

    html_url = str(issue.get("html_url") or "")
    return {
        "issue_number": number,
        "issue_url": html_url,
        "state": state,
        "title": str(issue.get("title") or "").strip(),
        "source_org": source,
        "url": url,
        "url_key": normalize_url(url),
        "date_published": date_published,
        "category": carried.get("Category", ""),
        "file_type": carried.get("File type", ""),
        "decision": decision,
        "decision_reason": fields.get("Reason", "").strip(),
        "summary": "\n".join(summary_lines).strip(),
        "legacy_sheet_url": legacy_sheet_url,
        "legacy_sheet_row": fields.get("Sheet row", "").strip(),
        "legacy_notes": legacy_notes,
        "blog_url": blog_url,
        "removed_duplicate": removed_duplicate,
        "axioms": bullets["axioms"],
        "invariables": bullets["invariables"],
        "principles": bullets["principles"],
        "opencre_topics": bullets["opencre_topics"],
    }


def _canonical_key(record: dict) -> tuple:
    return (
        1 if record["removed_duplicate"] else 0,
        0 if record["state"] == "open" else 1,
        0 if record["legacy_sheet_url"] else 1,
        record["issue_number"],
    )


def _clean_registry(registry: list[dict]) -> list[dict]:
    cleaned = []
    seen_ids: dict[str, int] = {}
    seen_issues: dict[int, str] = {}
    for entry in registry:
        wp_id = entry.get("wp_id")
        if not isinstance(wp_id, str) or not WP_ID_RE.fullmatch(wp_id):
            raise SystemExit(f"Registry id {wp_id!r} is not WP- and four digits.")
        if "issue_number" not in entry:
            raise SystemExit(f"{wp_id} is missing issue_number.")
        issue_number = int(entry["issue_number"])
        url_key = normalize_url(str(entry.get("url") or ""))
        if not url_key:
            raise SystemExit(f"{wp_id} has an empty URL.")
        if wp_id in seen_ids and seen_ids[wp_id] != issue_number:
            raise SystemExit(f"{wp_id} is already used and cannot move to another issue.")
        if issue_number in seen_issues and seen_issues[issue_number] != wp_id:
            raise SystemExit(f"Issue {issue_number} already has {seen_issues[issue_number]}.")
        seen_ids[wp_id] = issue_number
        seen_issues[issue_number] = wp_id
        cleaned.append({"wp_id": wp_id, "url": url_key, "issue_number": issue_number})
    cleaned.sort(key=lambda item: item["wp_id"])
    return cleaned


def _allocate(used: set[str]) -> str:
    number = 1
    while number <= 9999:
        wp_id = f"WP-{number:04d}"
        number += 1
        if wp_id not in used:
            used.add(wp_id)
            return wp_id
    raise SystemExit("The inventory ran out of WP- ids.")


def build_papers(records: list[dict], registry: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep registry ids. Fold a new issue into an existing URL. Mint an id for a new URL.

    Issues are walked in issue-number order. The first issue for a new URL gets
    the next free id. A later issue for that same URL shares the id, unless the
    registry already gave that later issue an id of its own.
    """
    stored = _clean_registry(registry)
    by_issue = {entry["issue_number"]: entry for entry in stored}
    by_url: dict[str, list[dict]] = {}
    for entry in stored:
        by_url.setdefault(entry["url"], []).append(entry)
    used = {entry["wp_id"] for entry in stored}

    owned: list[dict] = []
    pending: list[dict] = []
    for record in records:
        current = by_issue.get(record["issue_number"])
        if current is None:
            pending.append(record)
            continue
        if current["url"] != record["url_key"]:
            raise SystemExit(
                f"Issue {record['issue_number']} changed URL. "
                f"{current['wp_id']} stays on {current['url']}."
            )
        record["wp_id"] = current["wp_id"]
        record["duplicate_issue_numbers"] = []
        owned.append(record)

    grouped: dict[str, list[dict]] = {}
    for record in pending:
        grouped.setdefault(record["url_key"], []).append(record)

    new_entries: list[dict] = []
    owned_by_url: dict[str, list[dict]] = {}
    for record in owned:
        owned_by_url.setdefault(record["url_key"], []).append(record)

    def fold_into(members: list[dict], candidates: list[dict]) -> None:
        if not candidates:
            number = members[0]["issue_number"]
            raise SystemExit(f"Issue {number} has no paper to share a URL with.")
        canonical = sorted(candidates, key=_canonical_key)[0]
        for member in members:
            if member is canonical:
                continue
            canonical["duplicate_issue_numbers"].append(member["issue_number"])

    new_urls = sorted(
        (url_key for url_key in grouped if url_key not in by_url),
        key=lambda url_key: min(item["issue_number"] for item in grouped[url_key]),
    )
    for url_key in new_urls:
        members = grouped[url_key]
        canonical = sorted(members, key=_canonical_key)[0]
        canonical["wp_id"] = _allocate(used)
        canonical["duplicate_issue_numbers"] = []
        new_entries.append(
            {
                "wp_id": canonical["wp_id"],
                "url": url_key,
                "issue_number": canonical["issue_number"],
            }
        )
        owned.append(canonical)
        owned_by_url.setdefault(url_key, []).append(canonical)
        fold_into(members, [canonical])

    for url_key, members in grouped.items():
        if url_key in new_urls:
            continue
        fold_into(members, owned_by_url.get(url_key, []))

    for record in owned:
        record["duplicate_issue_numbers"] = sorted(set(record["duplicate_issue_numbers"]))

    merged = list(stored)
    merged.extend(new_entries)
    merged.sort(key=lambda entry: entry["wp_id"])
    return owned, merged


def paper_record(paper: dict) -> dict:
    """Public paper object, without the internal URL key."""
    return {
        "wp_id": paper["wp_id"],
        "issue_number": paper["issue_number"],
        "issue_url": paper["issue_url"],
        "state": paper["state"],
        "title": paper["title"],
        "source_org": paper["source_org"],
        "url": paper["url"],
        "date_published": paper["date_published"],
        "category": paper["category"],
        "file_type": paper["file_type"],
        "decision": paper["decision"],
        "decision_reason": paper["decision_reason"],
        "summary": paper["summary"],
        "legacy_sheet_url": paper["legacy_sheet_url"],
        "legacy_sheet_row": paper["legacy_sheet_row"],
        "legacy_notes": paper["legacy_notes"],
        "blog_url": paper["blog_url"],
        "duplicate_issue_numbers": list(paper["duplicate_issue_numbers"]),
        "axioms": list(paper["axioms"]),
        "invariables": list(paper["invariables"]),
        "principles": list(paper["principles"]),
        "opencre_topics": list(paper["opencre_topics"]),
    }


def build_inventory(
    issues: list[dict],
    registry: list[dict] | None = None,
    updated: str = "",
    repository: str | None = None,
) -> dict:
    records = [parse_issue(issue) for issue in issues]
    papers, id_registry = build_papers(records, list(registry or []))
    public = [paper_record(paper) for paper in papers]
    public.sort(key=lambda paper: paper["wp_id"])
    return {
        "version": SCHEMA_VERSION,
        "updated": updated,
        "source": SOURCE,
        "repository": repository or repository_slug(),
        "sheet": {
            "status": "retired",
            "retired_on": RETIRED_ON,
            "id": RETIRED_SHEET_ID,
        },
        "id_registry": id_registry,
        "papers": public,
    }


def load_inventory(path: Path = JSON_PATH) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_csv(document: dict, path: Path = CSV_PATH) -> None:
    import csv

    columns = [
        "wp_id",
        "issue_number",
        "issue_url",
        "state",
        "title",
        "source_org",
        "url",
        "date_published",
        "category",
        "file_type",
        "decision",
        "decision_reason",
        "summary",
        "legacy_sheet_url",
        "legacy_sheet_row",
        "legacy_notes",
        "blog_url",
        "duplicate_issue_numbers",
        "axioms",
        "invariables",
        "principles",
        "opencre_topics",
    ]
    list_columns = {"axioms", "invariables", "principles", "opencre_topics"}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for paper in document["papers"]:
            row = {}
            for column in columns:
                value = paper[column]
                if column == "duplicate_issue_numbers":
                    row[column] = ";".join(str(number) for number in value)
                elif column in list_columns:
                    row[column] = "\n".join(value)
                else:
                    row[column] = value
            writer.writerow(row)


def write_inventory(document: dict, json_path: Path = JSON_PATH, csv_path: Path = CSV_PATH) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(dump_json(document), encoding="utf-8")
    write_csv(document, csv_path)


def counts(document: dict) -> dict[str, int]:
    decisions = {"include": 0, "delete_candidate": 0, "duplicate": 0}
    folded = 0
    for paper in document["papers"]:
        decisions[paper["decision"]] += 1
        folded += len(paper["duplicate_issue_numbers"])
    return {
        "papers": len(document["papers"]),
        "registry": len(document["id_registry"]),
        "folded_duplicate_issues": folded,
        **decisions,
    }


def format_counts(document: dict) -> str:
    tally = counts(document)
    folded = tally["folded_duplicate_issues"]
    folded_label = "extra issue shares" if folded == 1 else "extra issues share"
    return (
        f"{tally['papers']} papers "
        f"({tally['include']} include, {tally['delete_candidate']} delete candidates, "
        f"{tally['duplicate']} duplicates); "
        f"{folded} {folded_label} a URL and did not get a new id; "
        f"{tally['registry']} WP- ids are reserved."
    )
