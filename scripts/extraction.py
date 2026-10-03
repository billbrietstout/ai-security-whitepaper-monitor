#!/usr/bin/env python3
"""Fetch documents for inventory rows with empty extraction columns, and write results back.

Used by the Cursor extraction pass in docs/extraction-prompt.md.

  worklist  Read the sheet, pick rows whose Axioms, Invariables, Principles, and
            OpenCRE Topics are all empty, download each Link, and save the text
            under work/extraction/.
  apply     Validate work/extraction/results.json. With --write, fill the four
            cells on rows that are still empty, save the evidence log under data/,
            and append one Changelog row.

Credentials: a service account key for the sheet, read from GOOGLE_APPLICATION_CREDENTIALS
or gspread's default path (~/.config/gspread/service_account.json). Keep it out of the repo.
"""

import argparse
import io
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import gspread
import requests
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "extraction"
TEXTS = WORK / "texts"
WORKLIST = WORK / "worklist.json"
RESULTS = WORK / "results.json"
DATA = ROOT / "data"

SHEET_ID = "161FFOVjQUNxiaOzMryT6sbEuYjq-uLf-vcDEHfvlFbE"
INVENTORY_TABS = ["MOSAIC", "Peer SDOs", "Government", "Coalitions", "Vendor labs"]
CHANGELOG_TAB = "Changelog"
EXTRACTION_COLUMNS = ["Axioms", "Invariables", "Principles", "OpenCRE Topics"]
LIST_COLUMNS = {"axioms": "Axioms", "invariables": "Invariables", "principles": "Principles"}
HEADERS = {"User-Agent": "cosai-monitor-extraction/1.0"}
MAX_TEXT_CHARS = 200_000

# Base labels the sheet already uses most. Keep in sync with docs/extraction-prompt.md.
OPENCRE_LABELS = [
    "Access Control", "Authentication", "Cryptography", "Data Protection",
    "Governance-Risk-Compliance", "Incident Response", "Input Validation",
    "Log Management", "Secrets Management", "Secure Product Design",
    "Session Management", "Supply Chain", "Threat Modeling",
    "Training and Awareness", "Vulnerability Management",
]
BULLETS_MIN, BULLETS_MAX = 3, 8
TOPICS_MIN, TOPICS_MAX = 1, 6
BULLET_MAX_CHARS = 240

# Project slop list (user writing rules): rewrite targets that fail validation.
BANNED = re.compile(
    r"\b(delve|dive into|unpack|leverag\w*|harness\w*|unlock\w*|foster\w*|empower\w*|elevat\w*|"
    r"streamlin\w*|navigat\w*|landscape|ecosystem|tapestry|realm|multifaceted|robust|seamless\w*|"
    r"cutting-edge|groundbreaking|holistic|comprehensive|end-to-end|pivotal|crucial|vital|"
    r"underscor\w*|highlight\w*|showcas\w*|illuminat\w*|best practices|industry standards|ensures?)\b",
    re.IGNORECASE,
)
DASHES = re.compile("[\u2013\u2014]")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")])
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    return urlunsplit((scheme, parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def open_sheet():
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    gc = gspread.service_account(filename=key_path) if key_path else gspread.service_account()
    return gc.open_by_key(SHEET_ID)


def column(header: list[str], name: str) -> int | None:
    return header.index(name) if name in header else None


def cell(row: list[str], idx: int | None) -> str:
    return row[idx].strip() if idx is not None and idx < len(row) else ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "doc"


# ---------------------------------------------------------------------------
# worklist
# ---------------------------------------------------------------------------

def fetch_text(url: str) -> tuple[str, str]:
    """Return (text, error). PDF text carries [page N] markers so bullets can cite pages."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        r.raise_for_status()
    except requests.RequestException as e:
        return "", f"fetch failed: {e}"

    is_pdf = "pdf" in r.headers.get("Content-Type", "").lower() or urlsplit(url).path.lower().endswith(".pdf")
    if is_pdf:
        # pdfminer keeps word spacing on LaTeX PDFs where pypdf runs words together.
        try:
            pages = []
            for i, layout in enumerate(extract_pages(io.BytesIO(r.content)), 1):
                page_text = "".join(el.get_text() for el in layout if isinstance(el, LTTextContainer))
                # Tables of contents come out as one dot-leader "." per line.
                page_text = "\n".join(l for l in page_text.splitlines() if l.strip(" .") or not l.strip())
                page_text = re.sub(r"\n{3,}", "\n\n", page_text)
                pages.append(f"[page {i}]\n{page_text.strip()}")
        except Exception as e:
            return "", f"PDF parse failed: {e}"
        text = "\n\n".join(pages)
        if len(re.sub(r"\[page \d+\]|\s", "", text)) < 500:
            return "", "PDF has no text layer (scanned?)"
    else:
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        # Pages can hold small <article> cards (related posts) beside the real body.
        blocks = soup.find_all(["article", "main"]) or [soup.body or soup]
        main = max(blocks, key=lambda el: len(el.get_text(" ", strip=True)))
        text = re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))
        if len(text) < 500:
            return "", "page has under 500 characters of text (script-rendered or blocked?)"

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[truncated]"
    return text, ""


def excluded_links() -> set[str]:
    """Links an earlier pass judged to fail the include rules; their cells stay empty on purpose."""
    links = set()
    for path in DATA.glob("extraction-evidence-*.json"):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if entry.get("include") is False:
                links.add(normalize_url(entry["link"]))
    return links


def cmd_worklist(args):
    sheet = open_sheet()
    tabs = [args.tab] if args.tab else INVENTORY_TABS
    skip = set() if args.recheck else excluded_links()
    skipped = 0
    items = []
    for tab in tabs:
        try:
            rows = sheet.worksheet(tab).get_all_values()
        except gspread.WorksheetNotFound:
            print(f"skip: tab {tab!r} not found")
            continue
        if not rows:
            continue
        header = rows[0]
        idx = {name: column(header, name) for name in
               ["#", "MOSAIC Member", "Organization", "Publication", "Category", "Link", *EXTRACTION_COLUMNS]}
        if idx["Link"] is None or any(idx[c] is None for c in EXTRACTION_COLUMNS):
            print(f"skip: tab {tab!r} lacks Link or an extraction column")
            continue
        for row in rows[1:]:
            link = cell(row, idx["Link"])
            if not link or any(cell(row, idx[c]) for c in EXTRACTION_COLUMNS):
                continue
            if args.link and normalize_url(link) != normalize_url(args.link):
                continue
            if normalize_url(link) in skip:
                skipped += 1
                continue
            items.append({
                "tab": tab,
                "number": cell(row, idx["#"]),
                "issuer": cell(row, idx["MOSAIC Member"]) or cell(row, idx["Organization"]),
                "publication": cell(row, idx["Publication"]),
                "category": cell(row, idx["Category"]),
                "link": link,
            })

    if skipped:
        print(f"skip: {skipped} rows already judged to fail the include rules (--recheck to include them)")
    items = items[: args.limit]
    TEXTS.mkdir(parents=True, exist_ok=True)
    for item in items:
        print(f"fetch {item['tab']} #{item['number']}: {item['publication'][:70]}")
        text, error = fetch_text(item["link"])
        item["fetch_error"] = error
        item["text_file"] = ""
        if text:
            path = TEXTS / f"{slug(item['tab'])}-{item['number'] or 'x'}-{slug(item['publication'])}.txt"
            path.write_text(text, encoding="utf-8")
            item["text_file"] = str(path.relative_to(ROOT))
            item["text_chars"] = len(text)
        else:
            print(f"  {error}")

    WORKLIST.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for i in items if i["text_file"])
    print(f"\n{len(items)} rows in {WORKLIST.relative_to(ROOT)}; {ok} with text, {len(items) - ok} with fetch errors")


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def validate(result: dict) -> list[str]:
    problems = []
    if not result.get("link"):
        return ["missing link"]
    if not isinstance(result.get("include"), bool):
        problems.append("include must be true or false")
    if not result.get("include_reason", "").strip():
        problems.append("include_reason is empty")
    if result.get("include") is not True:
        return problems

    for key, name in LIST_COLUMNS.items():
        bullets = result.get(key) or []
        if not BULLETS_MIN <= len(bullets) <= BULLETS_MAX:
            problems.append(f"{name}: {len(bullets)} bullets, need {BULLETS_MIN} to {BULLETS_MAX}")
        for b in bullets:
            text, ref = (b.get("text") or "").strip(), (b.get("ref") or "").strip()
            if not text:
                problems.append(f"{name}: empty bullet")
                continue
            if not ref:
                problems.append(f"{name}: no ref for {text[:50]!r}")
            if len(text) > BULLET_MAX_CHARS:
                problems.append(f"{name}: over {BULLET_MAX_CHARS} chars: {text[:50]!r}")
            if DASHES.search(text):
                problems.append(f"{name}: em or en dash in {text[:50]!r}")
            m = BANNED.search(text)
            if m:
                problems.append(f"{name}: banned word {m.group(0)!r} in {text[:50]!r}")
            if key == "axioms" and re.search(r"\b(must|never|shall)\b", text, re.I):
                problems.append(f"Axioms: must-style wording belongs in Invariables: {text[:50]!r}")
            if key == "principles" and ":" not in text:
                problems.append(f"Principles: use 'Name: actor, action, object, condition': {text[:50]!r}")

    topics = result.get("opencre_topics") or []
    if not TOPICS_MIN <= len(topics) <= TOPICS_MAX:
        problems.append(f"OpenCRE Topics: {len(topics)} labels, need {TOPICS_MIN} to {TOPICS_MAX}")
    for t in topics:
        if t not in OPENCRE_LABELS:
            problems.append(f"OpenCRE Topics: {t!r} is not an allowed label")
    return problems


def cell_values(result: dict) -> dict[str, str]:
    values = {name: "\n".join(f"- {b['text'].strip()}" for b in result[key]) for key, name in LIST_COLUMNS.items()}
    values["OpenCRE Topics"] = "\n".join(f"- {t}" for t in result["opencre_topics"])
    return values


def cmd_apply(args):
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    worklist = json.loads(WORKLIST.read_text(encoding="utf-8")) if WORKLIST.exists() else []
    by_link = {normalize_url(i["link"]): i for i in worklist}

    valid, errors = [], []
    for r in results:
        problems = validate(r)
        if r.get("link") and normalize_url(r["link"]) not in by_link:
            problems.append("link is not in worklist.json; copy it from the worklist item")
        title = by_link.get(normalize_url(r.get("link", "")), {}).get("publication") or r.get("link", "?")
        if problems:
            errors.append(f"{title[:60]}: " + "; ".join(problems))
        else:
            valid.append(r)

    print(f"{len(valid)} valid, {len(errors)} with problems")
    for e in errors:
        print(f"  FIX {e}")
    if not args.write:
        print("\nDry run. Fix the problems above, then rerun with --write.")
        return
    if errors and not args.skip_invalid:
        sys.exit("Refusing to write while results have problems. Fix them or pass --skip-invalid.")

    sheet = open_sheet()
    tabs = {ws.title: ws for ws in sheet.worksheets()}
    filled, excluded, skipped = [], [], []
    evidence = []
    for r in valid:
        item = by_link.get(normalize_url(r["link"]), {})
        title = item.get("publication") or r["link"]
        if not r["include"]:
            excluded.append(f"{title} ({r['include_reason'].strip()})")
            evidence.append({**r, "tab": item.get("tab"), "publication": title, "written": False})
            continue

        ws = tabs.get(item.get("tab", ""))
        rows = ws.get_all_values() if ws else []
        header = rows[0] if rows else []
        link_col = column(header, "Link")
        cols = {name: column(header, name) for name in EXTRACTION_COLUMNS}
        match = None
        for n, row in enumerate(rows[1:], start=2):
            if link_col is not None and normalize_url(cell(row, link_col)) == normalize_url(r["link"]):
                match = (n, row)
                break
        if not match or any(i is None for i in cols.values()):
            skipped.append(f"{title}: row not found on {item.get('tab')!r}")
            continue
        n, row = match
        if any(cell(row, i) for i in cols.values()):
            skipped.append(f"{title}: extraction cells no longer empty")
            continue

        values = cell_values(r)
        ws.batch_update(
            [{"range": gspread.utils.rowcol_to_a1(n, cols[name] + 1), "values": [[values[name]]]}
             for name in EXTRACTION_COLUMNS],
            value_input_option="RAW",
        )
        filled.append(title)
        evidence.append({**r, "tab": item.get("tab"), "publication": title, "written": True})
        print(f"filled {item.get('tab')} row {n}: {title[:70]}")

    today = date.today().isoformat()
    log_path = DATA / f"extraction-evidence-{today}.json"
    prior = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    log_path.write_text(json.dumps(prior + evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    fetch_errors = [f"{i['publication'][:60]}: {i['fetch_error']}" for i in worklist if i.get("fetch_error")]
    changelog = tabs.get(CHANGELOG_TAB)
    if changelog is not None:
        header = changelog.row_values(1)
        values = {
            "Date": today,
            "Trigger": "manual",
            "Orgs checked": "extraction pass",
            "Added": "none",
            "Updated": f"extraction filled on {len(filled)} rows: " + "; ".join(filled) if filled else "none",
            "Skipped": "; ".join(
                (["fails include rules, delete candidates: " + "; ".join(excluded)] if excluded else [])
                + skipped
            ) or "none",
            "Errors": "; ".join(fetch_errors + errors) or "none",
        }
        changelog.append_row([values.get(h, "") for h in header], value_input_option="RAW")

    print(f"\nfilled {len(filled)}, delete candidates {len(excluded)}, skipped {len(skipped)}")
    print(f"evidence log: {log_path.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("worklist", help="pick rows and download their documents")
    w.add_argument("--tab", choices=INVENTORY_TABS, help="only this inventory tab")
    w.add_argument("--limit", type=int, default=10, help="rows per batch (default 10)")
    w.add_argument("--link", help="only the row with this Link")
    w.add_argument("--recheck", action="store_true", help="also pick rows an earlier pass excluded")
    w.set_defaults(func=cmd_worklist)
    a = sub.add_parser("apply", help="validate results.json and optionally write it")
    a.add_argument("--write", action="store_true", help="write to the sheet (default is a dry run)")
    a.add_argument("--skip-invalid", action="store_true", help="write valid results even if others have problems")
    a.set_defaults(func=cmd_apply)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
