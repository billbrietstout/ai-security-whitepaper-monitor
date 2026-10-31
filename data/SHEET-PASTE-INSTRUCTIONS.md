# Paste into Google Sheet

The Google Sheet was retired on October 31, 2026. GitHub issues are the source of truth. Do not paste these files into the sheet. `scripts/sheet_sync.py` now exits without reading or writing the sheet. The current update process is in [README.md](../README.md). The rest of this file is a record of the old paste steps.

As of 2026-10-03, changes were written with `scripts/sheet_sync.py` (see "Writing to the sheet" in `docs/refresh-runbook.md`).

Spreadsheet: https://docs.google.com/spreadsheets/d/161FFOVjQUNxiaOzMryT6sbEuYjq-uLf-vcDEHfvlFbE/edit

## How to paste without row spill

Google Sheets clipboard paste uses **physical file lines** as row boundaries. It does not parse quoted multiline CSV fields.

**Use `*.tsv` paste files only.** Each inventory row is **one line** in the file. Extraction bullets are joined with ` · ` on a single line inside columns G–I. Turn on **Wrap text** on those columns after paste.

**Do not copy-paste from `*_import.csv` files.** Those files put each bullet on its own line inside quoted fields. When you copy from an editor, Sheets sees 40+ lines for 3 papers and fills column A down the sheet.

### Full row (recommended)

1. Select the target cell (e.g. **A2** on Peer SDOs).
2. Open the `*.tsv` file, select all, copy, paste.

### Two-step paste (if a full row is too wide)

1. Paste `*-cols-A-F.tsv` at **A2** (Organization through Link, 6 columns).
2. Paste `*-cols-G-K.tsv` at **G2** (Axioms through Blog, 5 columns).

Regenerate paste files after editing source data:

```bash
python3 scripts/build-paste-files.py
```

## Tab setup (if not done yet)

1. Rename **MOSAIC Publications** → **MOSAIC**
2. Add tabs: **Peer SDOs**, **Government**, **Coalitions**, **Vendor labs**, **Watch list**, **Changelog**
3. On **Peer SDOs**, **Government**, **Coalitions**, **Vendor labs**: paste row 1 from `data/inventory-tab-headers.tsv`
4. On **Watch list**: paste `data/watch-list-full.tsv` at **A1** (header, 8 MOSAIC, 12 Peer SDO/Coalition, 11 Government, 7 Vendor labs orgs; 39 lines). If MOSAIC rows are already present, append only `data/watch-list-peer-coalitions.tsv` at **A10** (12 lines, no header). For Government and Vendor labs, see the 2026-10-03 section below.
5. On **Changelog**: headers `Date`, `Trigger`, `Orgs checked`, `Added`, `Updated`, `Skipped`, `Errors`

## MOSAIC new rows (#42–48)

1. Open the **MOSAIC** tab
2. Select cell **A43**
3. Copy all **7 lines** from `data/mosaic-append-rows.tsv` and paste

## Restore row #41 CoSAI SRF

See **MOSAIC fixes — CoSAI link rotation, #41 SRF** below (paste at **A41**).

## SANS v1.4 update (row #39)

See **MOSAIC fixes** below (paste `sans-v1.4-row39-cols-CL.tsv` at **C39**).

- **Publication**: Critical AI Security Guidelines v1.4
- **Date Published**: March 2026
- **Link**: https://assets.contentstack.io/v3/assets/bltabe50a4554f8e97f/blte964a6eef293d57e/whitepaper-critical-ai-security-guidelines

## Missing tabs

Add **Government** and **Vendor labs** if not present. Paste row 1 from `data/inventory-tab-headers.tsv` on each.

Tab order: MOSAIC, Peer SDOs, Government, Coalitions, Vendor labs, Watch list, Changelog.

## Changelog

Done: rows 2 to 4 (2026-08-31, 2026-09-01, 2026-09-01 MOSAIC fixes) and row 14 (2026-10-03 seed) are on the sheet. Do not paste the 2026-08-31 or 2026-09-01 changelog files again. The only Changelog file still to append is `data/changelog-manual-2026-10-03-refresh.tsv`.

## Peer SDO / Coalition watch list refresh (2026-09-01)

After the 12 org rows are on **Watch list** (rows 10–21 if MOSAIC rows are 2–9):

**Update Catalog URL, Last checked, Notes only:**

1. Select **C10**
2. Copy all **12 lines** from `data/watch-list-peer-coalitions-cols-CE.tsv` and paste

**Replace all 12 peer/coalition rows:**

1. Select **A10**
2. Copy all **12 lines** from `data/watch-list-peer-coalitions-2026-09-01.tsv` and paste

**Changelog:** done (row 3).

## Peer SDOs + Coalitions priority-1 inventory (2026-09-01)

Paste **after row 1 headers** from `data/inventory-tab-headers.tsv`.

**Peer SDOs tab (3 rows):**

1. Select **A2**
2. Copy all **3 lines** from `data/peer-sdos-priority1.tsv` and paste

Two-step alternative: `peer-sdos-priority1-cols-A-F.tsv` at **A2**, then `peer-sdos-priority1-cols-G-K.tsv` at **G2**.

**Coalitions tab (5 rows):**

1. Select **A2**
2. Copy all **5 lines** from `data/coalitions-priority1.tsv` and paste

Two-step alternative: `coalitions-priority1-cols-A-F.tsv` at **A2**, then `coalitions-priority1-cols-G-K.tsv` at **G2**.

Regenerate: `python3 scripts/generate-priority1-inventory.py`

## MOSAIC fixes — CoSAI link rotation, #41 SRF, #39 SANS v1.4 (2026-09-01)

**Problem:** Rows 14–20 have rotated Link cells (each paper points at the next file). Row 41 on the live sheet holds SANS Critical AI Security Guidelines v1.4 under CoSAI; **CoSAI SRF v1.0** belongs on MOSAIC as #41. Row 39 may still be v1.2.

### 1. Fix Link column rows 14–20

1. Open **MOSAIC** tab
2. Confirm that `#` 14 through `#` 20 sit on consecutive rows in that order. In the 2026-08-31 snapshot they are sheet rows 15 to 21.
3. Select the **Link** cell (column **G**) on the row whose `#` is 14 (**G15** in the snapshot layout)
4. Copy all **7 lines** from `data/mosaic-cosai-links-fix-col-G.tsv` and paste

| Row | Publication (short) | Correct Link target |
|-----|----------------------|---------------------|
| 14 | CSA Mythos-ready CISO briefing | labs.cloudsecurityalliance.org/mythos-ciso |
| 15 | CoSAI AI supply chain risks | ws1 …/risks-and-controls-for-the-ai-supply-chain-v1.md |
| 16 | Signing ML Artifacts | ws1 …/signing-ml-artifacts.md |
| 17 | Preparing Defenders | ws2 …/preparing-defenders-of-ai-systems.md |
| 18 | AI Incident Response | ws2 …/incident-response/AI Incident Response.md |
| 19 | Secure-by-Design Agentic Principles | cosai-tsc …/security-principles-for-agentic-systems.md |
| 20 | MCP Security | ws4 …/model-context-protocol-security.md |

Rows 21–22 links are already correct (coalitionforsecureai.org PDFs).

### 2. Restore #41 CoSAI SRF v1.0

1. Find the row whose `#` cell is 41 and select its column **A** cell. Sheet row numbers do not match `#` values on this tab; `#` n is usually on row n+1, but the snapshot is out of order.
2. Copy the **single line** from `data/cosai-srf-row41.tsv` and paste (replaces misplaced SANS v1.4 / CoSAI attribution)

### 3. Update #39 SANS v1.4 (if still v1.2)

1. Find the row whose `#` cell is 39 and select its column **C** cell (sheet row 41 in the snapshot, so **C41**)
2. Copy the **single line** from `data/sans-v1.4-row39-cols-CL.tsv` and paste (Publication through Blog; keeps `#` and `SANS Institute`)

**Changelog:** done (row 4).

## MOSAIC Date Published repair, #1 to #48 (2026-10-03)

A date format on column D turned year-only cells (2024, 2025, 2026) into July 1905 dates and replaced text such as "Aug 2019" with m/d/yy.

1. Select **D2:D49** on **MOSAIC**
2. Format > Number > **Plain text** (do this first, or Sheets converts the text again)
3. Select **D2**, copy all **48 lines** from `data/mosaic-date-col-D-rows-1-48.tsv`, and paste

Rows `#49` and later came from the GitHub monitor and are not covered by this file.

## Refresh run (2026-10-03)

Findings per tab: `work/refresh-2026-10-03/findings-*.md`.

**Watch list:** select **C2**, paste all **38 lines** from `data/watch-list-refresh-2026-10-03-cols-C-E.tsv` (Catalog URL, Last checked, Notes). Rows must still be in the order seeded on 2026-10-03. Nine Catalog URLs change: CSA, ETSI, ISO, IEEE, ITU-T, MLCommons, CISA, CAISI, SEI.

**MOSAIC links** (column G; sheet row is `#` + 1):

1. Select **G15** (`#` 14) and paste all **7 lines** from `data/mosaic-cosai-links-fix-col-G.tsv`. CoSAI moved four GitHub files into `whitepapers/` folders after the 2026-09-01 fix.
2. **G27** (`#` 26): `https://csrc.nist.gov/pubs/ai/100/2/e2025/final`
3. **G44** (`#` 43): `https://github.com/OWASP/AISVS/raw/main/1.0/dist/AISVS-1.0.pdf`

**New inventory rows.** Before each paste, set the target Date Published cells to Format > Number > **Plain text**, or Sheets turns "September 2026" into a date.

| Tab | Select | File | Lines |
|-----|--------|------|-------|
| MOSAIC | **A108** (`#` 107) | `data/refresh-2026-10-03-mosaic-add.tsv` | 4 |
| Peer SDOs | **A2** (replaces ATLAS v2026.08) | `data/refresh-2026-10-03-peer-sdos-replace.tsv` | 1 |
| Peer SDOs | **A5**, after deleting duplicate rows 5 to 9 (see below) | `data/refresh-2026-10-03-peer-sdos-add.tsv` | 1 |

As of 2026-10-03 14:30, Peer SDOs rows 5 to 9 repeat the five Coalitions rows (OpenSSF, FMF twice, PAI, AI Verify). Delete those rows on Peer SDOs; the Coalitions tab already has them.

If a paste lands in one cell or splits wrongly, copy from the terminal instead of the editor, which can add rich-text formatting that Sheets reads first: `pbcopy < data/<file>.tsv`, then paste with Cmd+V.
| Coalitions | **A7** | `data/refresh-2026-10-03-coalitions-add.tsv` | 3 |

Bullet source references: `data/extraction-evidence-2026-10-03.json`. Regenerate with `python3 scripts/results-to-paste.py work/refresh-2026-10-03 --date 2026-10-03 --mosaic-start 107`.

**Changelog:** append `data/changelog-manual-2026-10-03-refresh.tsv`.

## Government + Vendor labs watch list seed (2026-10-03)

If **Watch list** already has rows 1 to 21 (header, 8 MOSAIC, 12 Peer SDO/Coalition):

1. Select **A22**
2. Copy all **18 lines** from `data/watch-list-government-vendor.tsv` and paste (11 Government rows, then 7 Vendor labs rows)

**Last checked** is blank on purpose. A blank date means nobody has compared the catalog against the inventory tab yet. Fill it with the date of the first real diff.

Three rows need a browser check because scripts cannot reach them: NSA AISC and OpenAI return 403, and cyber.gov.au did not connect.

**Changelog:** done (row 14).

Edit these rows in `GOV_VENDOR_WATCH` in `scripts/build-paste-files.py`, then regenerate. Hand edits to the TSV are overwritten on the next build.
