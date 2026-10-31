# AI Security Whitepaper Monitor

Last updated: October 31, 2026

## What this repo is

This repo is the source of truth for the AI security whitepaper inventory. Each paper is a GitHub issue in this repo. `data/whitepapers.json` and `data/whitepapers.csv` are built from those issues.

The papers come from CoSAI and its MOSAIC partners, OWASP, SANS, CSA, CIS, BIML, government agencies such as NIST and CISA, vendor labs, peer standards bodies and coalitions.

Grok Bot adds and updates papers by filing issues here. A person can do the same.

The Google Sheet `161FFOVjQUNxiaOzMryT6sbEuYjq-uLf-vcDEHfvlFbE` was retired on October 31, 2026. No script in this repo reads that sheet or writes to it. Leave the sheet as a historical file.

## What an issue contains

Open issues are papers in the inventory. Closed issues are delete candidates (papers marked for removal) or duplicates.

Put the organization on a `Source:` line and the paper URL on a `Link:` line:

```
**Source:** organization name
**Link:** https://example.org/paper.pdf
**Date published:** March 2026
```

The paper URL is the `Link:` line. Some older issues also have a hidden line:

```
<!-- sheet-url: URL -->
```

That line records the URL from the old sheet row. The export reads it when the line is present. A new issue can omit it.

Each paper has a stable id such as `WP-0001`. The id is tied to the paper's URL and to the issue that received it. The same issue keeps the same id from one export to the next. An id stays on that URL for the life of the inventory, including after the issue is closed.

Ids already in use on October 30, 2026 are kept. Issue 1 is `WP-0001`. Issue 161 is `WP-0154`. Six URLs were filed twice, and each copy kept its own id. A later issue for a URL that already has an id does not get a second id. A new URL receives the next free id. Issues 162 through 172 are `WP-0161` through `WP-0171`.

A private GitHub Project board may still show Status, Source org, URL, Date published, SRF layer, and Decision. The issues in this repo are public. The export reads the issue, not the board.

## How to update the inventory

1. Open an issue for a new paper, or edit the issue for a paper that changed. Use the `Source:` and `Link:` lines above. The issue title is the paper title.
2. To drop a paper, close its issue and add these lines:

```
**Decision:** Delete candidate
**Reason:** one sentence on why it is out
```

3. To mark a duplicate announcement, close its issue and add these lines:

```
**Decision:** Duplicate
**Reason:** name the paper that this issue repeats
```

4. From a checkout of this repo, rebuild the export:

```bash
python3 scripts/export_whitepapers.py
```

The script uses `GITHUB_TOKEN` or `GH_TOKEN` when one of those variables is set. If neither is set, it uses the `gh` login already on the machine. The script keeps the token out of its output.

To print counts without writing files:

```bash
python3 scripts/sync_issues.py
```

5. Commit `data/whitepapers.json` and `data/whitepapers.csv`, and open a pull request.

GitHub Actions runs the check named `validate-whitepapers` on every push and every pull request. The check does three things:

- It validates `data/whitepapers.json` against `schemas/whitepapers.schema.json`.
- It checks that each `WP-` id is unique, and that an id already tied to a URL stays on that URL.
- It checks that every record points at an issue that exists in this repo, and that the export matches those issues.

`scripts/validate_whitepapers.py` is the same check. It needs the token the same way the export does. Set `VALIDATION_BASE_REF` when the last accepted export is on a branch other than `master`.

## Files

- `data/whitepapers.json` is the versioned inventory. `version` is the file format. `updated` is the date the file was written. `id_registry` lists every `WP-` id, the issue that received it, and the URL it belongs to. The registry keeps an id after a paper drops out of the issue list, so the id is not given to a different URL.
- `data/whitepapers.csv` is the same papers in a spreadsheet, one row per paper, keyed by `WP-` id.
- `schemas/whitepapers.schema.json` is the contract for the JSON file.
- `scripts/export_whitepapers.py` writes the JSON and CSV files.
- `scripts/sync_issues.py` reads the issues and prints counts. It does not write files and it does not edit issues.
- `scripts/validate_whitepapers.py` is the check that CI runs.
- `scripts/requirements.txt` lists the packages the check installs.
- `data/` also holds paste files, watch lists, change logs and extraction notes from before October 31, 2026. Those files record the old sheet work. The live inventory is the issues and `data/whitepapers.json`.
- `scripts/sheet_sync.py` and `scripts/extraction.py` stop immediately. They used to read and write the sheet.

## Branch protection

The default branch in this repo is `master`. Protect `master` so a direct push cannot skip the check. A commit cannot turn that setting on. Set it in GitHub. If you later rename the default branch to `main`, use the same rules on `main`.

1. Open Settings, then Rules, then Rulesets. (A classic branch protection rule under Branches is the same idea.)
2. Add a ruleset that targets the default branch, `master`.
3. Require a pull request before merging.
4. Require the status check `validate-whitepapers` to pass before merging.
5. Do not allow administrators to bypass the rule, unless you have a written reason to keep a bypass.

## License

The license for this data is not set yet. This repo has no LICENSE file.

