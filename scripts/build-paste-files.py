#!/usr/bin/env python3
"""Build local paste files from the old sheet workflow.

The Google Sheet was retired on 2026-10-31. This script does not call the
sheet. The live inventory is GitHub issues. See README.md.

Build Google Sheets paste/import data files.

Paste TSV: one physical line per inventory row (no \\n or \\r inside the row).
Multiline extraction fields are joined with middle dots so copy-paste stays on
one row and one column per field.

Import CSV: RFC CSV with real newlines inside quoted fields. Do not copy-paste
from these files in an editor; Google Sheets treats each file line as a row.
Use paste TSV for clipboard workflow.
"""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def flatten_for_paste(value: str) -> str:
    if not value:
        return ""
    s = value.replace("\r\n", "\n").replace("\r", "\n")
    parts = [part.strip() for part in s.split("\n") if part.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " · ".join(parts)


def write_inventory_splits(stem: Path, rows: list[list[str]]) -> None:
    """Write column-split paste files for two-step paste (A–F then G–K)."""
    base = stem.name.removesuffix(".tsv")
    write_paste_tsv(stem.with_name(f"{base}-cols-A-F.tsv"), [r[0:6] for r in rows])
    write_paste_tsv(stem.with_name(f"{base}-cols-G-K.tsv"), [r[6:11] for r in rows])


def row_to_paste_line(row: list[str], delimiter: str = "\t") -> str:
    parts: list[str] = []
    for field in row:
        s = flatten_for_paste(field)
        if delimiter in s or "\n" in s or "\r" in s or '"' in s:
            s = '"' + s.replace('"', '""') + '"'
        parts.append(s)
    line = delimiter.join(parts)
    if "\n" in line or "\r" in line:
        raise ValueError("paste line contains line-break characters")
    return line


def write_paste_tsv(path: Path, rows: list[list[str]]) -> int:
    with path.open("w", encoding="utf-8", newline="") as f:
        for row in rows:
            f.write(row_to_paste_line(row) + "\n")
    return len(rows)


def write_import_csv(path: Path, rows: list[list[str]]) -> int:
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return len(rows)


def read_snapshot_row(num: str) -> list[str]:
    with (ROOT / ".sheet-snapshot.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and row[0] == num:
                return row
    raise KeyError(f"row #{num} not in snapshot")


def read_tsv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f, delimiter="\t", quotechar='"'))


def read_mosaic_append_rows() -> list[list[str]]:
    import_csv = DATA / "mosaic-append-rows_import.csv"
    if import_csv.exists():
        with import_csv.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if len(rows) == 7:
            return rows
    rows = read_tsv_rows(DATA / "mosaic-append-rows.tsv")
    if len(rows) != 7:
        raise ValueError(f"expected 7 mosaic rows, got {len(rows)}")
    return rows


def read_sans_v14_row() -> list[str]:
    import_csv = DATA / "sans-v1.4-row39_import.csv"
    if import_csv.exists():
        with import_csv.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if rows and len(rows[0]) >= 12:
            return rows[0]
    path = DATA / "sans-v1.4-row39.tsv"
    rows = read_tsv_rows(path)
    if rows and len(rows[0]) >= 12:
        return rows[0]
    # Fallback: parse from known sans source file content
    raw = path.read_text(encoding="utf-8")
    rows = list(csv.reader(raw.splitlines(), delimiter="\t"))
    if not rows:
        raise ValueError("sans row missing")
    return rows[0]


GOV_VENDOR_WATCH = [
    ["Cybersecurity and Infrastructure Security Agency (CISA)", "Government", "https://www.cisa.gov/ai", "",
     "Joint guides with NSA, NCSC, and Five Eyes partners (Deploying AI Systems Securely 2024-04; AI Data Security 2025-05). Log each joint guide once, on this row."],
    ["UK National Cyber Security Centre (NCSC)", "Government", "https://www.ncsc.gov.uk/section/advice-guidance/all-topics", "",
     "Filter topic to Artificial intelligence. Anchor paper: Guidelines for Secure AI System Development (2023-11). Joint CISA/NCSC guides go under CISA."],
    ["NIST Center for AI Standards and Innovation (CAISI)", "Government", "https://www.nist.gov/caisi", "",
     "Renamed from US AISI in 2025. Track evaluation reports and agent hijacking work. NIST AI RMF and SP 800 papers stay on the MOSAIC tab."],
    ["UK AI Security Institute (AISI)", "Government", "https://www.aisi.gov.uk/research", "",
     "Record research papers and evaluation reports with a PDF or arXiv link; skip short blog updates."],
    ["Federal Office for Information Security (BSI), Germany", "Government", "https://www.bsi.bund.de/EN/Themen/Unternehmen-und-Organisationen/Informationen-und-Empfehlungen/Kuenstliche-Intelligenz/kuenstliche-intelligenz_node.html", "",
     "AIC4 criteria catalogue and LLM threat papers. English page can lag the German page; compare both when checking."],
    ["National Cybersecurity Agency of France (ANSSI)", "Government", "https://cyber.gouv.fr/nous-connaitre/publications/", "",
     "Filter for IA. Anchor paper: Security Recommendations for a Generative AI System (2024-04). Many papers are French only; record the French title."],
    ["Carnegie Mellon SEI / CERT Division", "Government", "https://insights.sei.cmu.edu/library/", "",
     "Filter topic to AI engineering. Record technical reports and white papers; most library entries are blog posts and podcasts."],
    ["NSA Artificial Intelligence Security Center (AISC)", "Government", "https://www.nsa.gov/AISC/", "",
     "Scripted fetch returns 403; check in a browser. AISC leads or co-seals CISA joint guides; log those under CISA, not here."],
    ["Australian Signals Directorate (ASD ACSC)", "Government", "https://www.cyber.gov.au/resources-business-and-government/governance-and-user-education/artificial-intelligence", "",
     "Script could not connect on 2026-10-03; confirm the URL in a browser. Co-author on Five Eyes joint AI guides."],
    ["Canadian Centre for Cyber Security", "Government", "https://www.cyber.gc.ca/en/guidance", "",
     "Filter for artificial intelligence. Co-author on Five Eyes joint guides; record only papers Canada publishes alone."],
    ["Cyber Security Agency of Singapore (CSA SG)", "Government", "https://www.csa.gov.sg/resources/publications", "",
     "Anchor papers: Guidelines and Companion Guide on Securing AI Systems (2024-10). AI Verify Foundation papers go on the Coalitions tab."],
    ["Google", "Vendor labs", "https://saif.google/", "",
     "Secure AI Framework (SAIF) hub: SAIF papers and risk map. Skip Vertex AI and Gemini product docs and model cards."],
    ["Microsoft", "Vendor labs", "https://learn.microsoft.com/en-us/security/ai-red-team/", "",
     "AI Red Team guidance and failure mode taxonomy. Second source: security blog AI topic (microsoft.com/en-us/security/blog/topic/ai-and-machine-learning/). Skip Azure product docs."],
    ["OpenAI", "Vendor labs", "https://openai.com/safety/", "",
     "Scripted fetch returns 403; check in a browser. Track Preparedness Framework revisions and security research papers. Skip system cards."],
    ["Anthropic", "Vendor labs", "https://www.anthropic.com/research", "",
     "Track Responsible Scaling Policy revisions at anthropic.com/responsible-scaling-policy and security research papers. Skip model cards."],
    ["Meta", "Vendor labs", "https://github.com/meta-llama/PurpleLlama", "",
     "Purple Llama repo links the CyberSecEval, Llama Guard, and LlamaFirewall papers. Record the papers, not the tool releases."],
    ["Amazon Web Services (AWS)", "Vendor labs", "https://aws.amazon.com/ai/generative-ai/security/", "",
     "Generative AI Security Scoping Matrix and AWS security whitepapers on generative AI. Skip Bedrock service docs."],
    ["NVIDIA", "Vendor labs", "https://developer.nvidia.com/blog/tag/ai-red-team/", "",
     "AI Red Team posts and the garak LLM scanner (github.com/NVIDIA/garak). Record standalone guidance posts and papers; skip product release notes."],
]


def main() -> None:
    cosai = read_snapshot_row("41")
    write_paste_tsv(DATA / "cosai-srf-row41.tsv", [cosai])
    write_import_csv(DATA / "cosai-srf-row41_import.csv", [cosai])

    mosaic = read_mosaic_append_rows()
    write_paste_tsv(DATA / "mosaic-append-rows.tsv", mosaic)
    write_import_csv(DATA / "mosaic-append-rows_import.csv", mosaic)

    sans = read_sans_v14_row()
    write_paste_tsv(DATA / "sans-v1.4-row39.tsv", [sans])
    write_paste_tsv(DATA / "sans-v1.4-row39-cols-CL.tsv", [sans[2:12]])
    write_import_csv(DATA / "sans-v1.4-row39_import.csv", [sans])

    dates = {str(n): read_snapshot_row(str(n))[3] for n in range(1, 42)}
    dates["39"] = sans[3]
    dates.update({r[0]: r[3] for r in mosaic})
    write_paste_tsv(
        DATA / "mosaic-date-col-D-rows-1-48.tsv", [[dates[str(n)]] for n in range(1, 49)]
    )

    wl = read_tsv_rows(DATA / "watch-list-seed.tsv")
    write_paste_tsv(DATA / "watch-list-seed.tsv", wl)

    peer = read_tsv_rows(DATA / "watch-list-peer-coalitions.tsv")
    write_paste_tsv(DATA / "watch-list-peer-coalitions.tsv", peer)

    wl_data = [r for r in wl if r and r[0] != "Organization"]
    watch_header = ["Organization", "Tab", "Catalog URL", "Last checked", "Notes"]
    write_paste_tsv(DATA / "watch-list-government-vendor.tsv", GOV_VENDOR_WATCH)
    write_paste_tsv(
        DATA / "watch-list-full.tsv", [watch_header] + wl_data + peer + GOV_VENDOR_WATCH
    )
    write_paste_tsv(
        DATA / "changelog-manual-2026-10-03.tsv",
        [[
            "2026-10-03",
            "manual",
            "none (watch-list seed only)",
            "Watch list: 11 Government and 7 Vendor labs sources",
            "none",
            "none",
            "nsa.gov and openai.com return 403 to scripts; cyber.gov.au did not connect",
        ]],
    )
    write_paste_tsv(
        DATA / "changelog-manual-2026-10-03-refresh.tsv",
        [[
            "2026-10-03",
            "manual",
            "38 (all Watch list rows)",
            "MOSAIC #107 CoSAI AIMM, #108 OWASP Agent Control Standard, #109 OWASP Framework Crosswalk, #110 SANS Quantifying Agentic Misalignment; Peer SDOs ETSI TS 104 275; Coalitions OpenSSF SAF-MCP, MLCommons Agent Privacy Risk Taxonomy, FMF Agents for Cyber Defense",
            "Peer SDOs MITRE ATLAS v2026.08 to v2026.09; MOSAIC links #15, #16, #18, #20, #26, #43; MOSAIC Date Published text restored on #1 to #48; Peer SDOs duplicate Coalitions rows removed (5); 9 Watch list catalog URLs",
            "excluded: CIS AI and human trafficking paper, SANS AI-powered pen testing paper, ENISA Threat Landscape 2026; not added: SANS Zero Trust and AI in Cloud, SANS Agentic Security Detection and Response (login wall, may be slides)",
            "nsa.gov, media.defense.gov, openai.com 403; cyber.gov.au and asd.gov.au HTTP/2 error; iso.org Cloudflare",
        ]],
    )

    hdr = [
        "Organization",
        "Publication",
        "Date Published",
        "Category",
        "File Type",
        "Link",
        "Axioms",
        "Invariables",
        "Principles",
        "OpenCRE Topics",
        "Blog / Announcement",
    ]
    write_paste_tsv(DATA / "inventory-tab-headers.tsv", [hdr])

    with (DATA / "changelog-manual-2026-08-31.csv").open(newline="") as f:
        cl = next(csv.reader(f))
    write_paste_tsv(DATA / "changelog-manual-2026-08-31.tsv", [cl])

    peer_refresh = read_tsv_rows(DATA / "watch-list-peer-coalitions-2026-09-01.tsv")
    write_paste_tsv(DATA / "watch-list-peer-coalitions-2026-09-01.tsv", peer_refresh)
    write_paste_tsv(DATA / "watch-list-peer-coalitions-cols-CE.tsv", [r[2:5] for r in peer_refresh])

    with (DATA / "changelog-manual-2026-09-01.csv").open(newline="") as f:
        cl09 = next(csv.reader(f))
    write_paste_tsv(DATA / "changelog-manual-2026-09-01.tsv", [cl09])

    import importlib.util

    _gen_spec = importlib.util.spec_from_file_location(
        "generate_priority1", ROOT / "scripts" / "generate-priority1-inventory.py"
    )
    _gen = importlib.util.module_from_spec(_gen_spec)
    _gen_spec.loader.exec_module(_gen)
    _gen.main()

    for name in [
        "cosai-srf-row41.tsv",
        "sans-v1.4-row39.tsv",
        "sans-v1.4-row39-cols-CL.tsv",
        "mosaic-append-rows.tsv",
        "mosaic-date-col-D-rows-1-48.tsv",
        "changelog-manual-2026-08-31.tsv",
        "inventory-tab-headers.tsv",
        "watch-list-seed.tsv",
        "watch-list-peer-coalitions.tsv",
        "watch-list-peer-coalitions-2026-09-01.tsv",
        "watch-list-peer-coalitions-cols-CE.tsv",
        "watch-list-full.tsv",
        "watch-list-government-vendor.tsv",
        "changelog-manual-2026-09-01.tsv",
        "changelog-manual-2026-10-03.tsv",
        "peer-sdos-priority1.tsv",
        "coalitions-priority1.tsv",
    ]:
        lines = (DATA / name).read_text(encoding="utf-8").splitlines()
        print(f"{name}: {len(lines)} physical line(s)")


if __name__ == "__main__":
    main()
