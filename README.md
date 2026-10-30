# AI Security Whitepaper Monitor

Last updated: October 30, 2026

## What this repo is

This repo tracks AI security whitepapers. The papers come from:

- CoSAI and its MOSAIC partners
- OWASP, SANS, CSA, CIS and BIML
- Government agencies, such as NIST and CISA
- Vendor labs
- Peer standards bodies
- Coalitions

The source list is a Google Sheet that Bill Stout maintains. This repo turns the sheet into GitHub issues so the papers are easy to search, link and track.

## What's in it

**Issues.** Each paper has one issue.

- Open issues are papers we include in the inventory.
- Closed issues are delete candidates (papers marked for removal) or duplicates.

Each issue body has a hidden marker in this form:

```
<!-- sheet-url: URL -->
```

The sync uses this marker to match an issue to its row in the sheet. That way it updates an existing issue instead of making a second one.

**Fields.** Each paper also has these fields on a tracking board:

- Status: New, Extracting, Reviewed or Done
- Source org: CoSAI, OWASP, SANS, CSA, CIS, BIML, Government, Vendor Lab, Peer SDO or Coalition
- URL
- Date published
- SRF layer: L1 to L5 (not filled in yet)
- Decision: Include or Delete candidate

The tracking board is a private GitHub Project, so you may not be able to see it. The issues in this repo are public.

**IDs.** Each paper has a stable ID, such as `WP-0001`. The ID is tied to the paper's URL, so it stays the same from one run to the next.

**Export.** A JSON and CSV export of all papers, keyed by WP- ID, is built each run. The export is not stored in this repo yet. It lives in the maintainer's working files.

**Folders.**

- `data/`: working files from past update runs, such as paste files, watch lists, change logs and extraction evidence
- `docs/`: the extraction prompt, the refresh runbook and notes on pending rows
- `scripts/`: helper scripts for extraction and for building sheet paste files

## How updates work

1. **Monday:** a monitor checks CoSAI, MOSAIC partners and related sources for new papers. It adds what it finds to the sheet.
2. **Tuesday:** an extraction pass fills in empty rows in the sheet, flags delete candidates and adds a row to the sheet's change log.
3. **Sync:** a script creates or updates one issue per paper, closes delete candidates and duplicates, and sets the board fields.
4. **Export:** the JSON and CSV export is rebuilt.
5. **Notice:** a downstream knowledge base is told which WP- IDs changed.

This README is updated when the process or contents change.

## License

The license for this data is not set yet. This repo has no LICENSE file.
