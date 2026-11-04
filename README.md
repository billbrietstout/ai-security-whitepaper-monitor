# AI Security Whitepaper Monitor

Last updated: November 4, 2026

## What this repo is

This repo is the source of truth for the AI security whitepaper inventory. Each paper is a GitHub issue in this repo. `data/whitepapers.json` and `data/whitepapers.csv` are built from those issues.

The papers come from CoSAI and its MOSAIC partners, OWASP, SANS, CSA, CIS, BIML, government agencies such as NIST and CISA, vendor labs, peer standards bodies and coalitions.

Grok Bot adds and updates papers by filing issues here. A person can do the same.

The inventory also holds arXiv papers that the monitored papers cite. These are filed as issues with `(arXiv ID)` at the end of the title.

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

An issue opened by `scripts/file_issues.py` also has this hidden line:

```
<!-- wp-id: WP-0542 -->
```

The line is the marker for that WP- id. The script searches issue bodies for the marker before it opens an issue. When the issue is new and the id is free, the export keeps the id from the marker. When the line is absent, the export assigns the next free id.

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

The export also reads a closed issue with the GitHub label `duplicate` as a duplicate when the Decision line is absent.

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

`scripts/validate_whitepapers.py` is the same check. Install its dependency once per environment:

```bash
python3 -m pip install -r scripts/requirements.txt
```

Then run the full check, or the local schema check:

```bash
python3 scripts/validate_whitepapers.py
python3 scripts/validate_whitepapers.py --schema-only
```

The full check needs the token the same way the export does. `--schema-only` checks the schema and the WP- id rules and does not call GitHub. Set `VALIDATION_BASE_REF` when the last accepted export is on a branch other than `master`.

## Weekly pass

Grok Bot runs a weekly pass. Screen papers first, then file one batch at a time. The filing command writes `runs/<date>.json` after every issue and every project add. Run it again to continue. It does not start the queue over.

Screening rules:

1. Check the tracked organizations for new AI security guidance. Skip press releases, events, vendor blogs, catalog pages and duplicates.
2. Collect the arXiv papers that each monitored paper cites. Look each one up in the arXiv API and go one level deep only. Do not follow the references of a cited paper.
3. Screen those arXiv papers with the same include rules. Compare them with all open and closed issues by URL and arXiv ID.
4. For each paper that passes, add an item to a queue file. The issue title for an arXiv paper ends with `(arXiv ID)`. You can set `arxiv_id`, `cited_by`, and `evidence_level` on the queue item. The filed issue then has an `arXiv reference` section with the arXiv ID, the monitored issues that cite it, and an evidence level.
5. Fill empty Axioms, Invariants, Principles and OpenCRE Topics fields from the source when you edit an issue by hand. The issue heading is `### Invariants`. Older issues may still say `### Invariables`; the export reads that heading too. A section is still empty when its only line is `_Not filled yet._`, `Not extracted yet.`, or `Not extracted yet. The next pass will fill this from the paper.` Each real bullet starts with `- `. A wrapped line with no dash continues the bullet above it. A line with no dash and no bullet above it is left out. The filing command does not close or delete an issue, and it does not edit an issue that already exists.

Evidence levels:

- `theoretical` means the work argues, surveys or proposes, with no new experiments.
- `tested` means the work ran experiments or evaluations.
- `tested, possibly deployed (needs review)` means the work ran experiments, and deployment words in the text are not confirmed yet.
- `deployed` means the work tested real deployed systems or reports results from production.

The level is judged from what the work did, not from its abstract. An organization guidance document with no experiments is `theoretical`, unless it reports tested or deployed practice. A level marked `provisional` or `needs review` came from an automated read of the paper text and has not been checked by a person yet. Every included paper needs one of these levels. The line is `- Evidence level: ...` under `### arXiv reference` or `### Evidence`. The export copies that section into `legacy_notes`.

```bash
python3 scripts/missing_evidence.py
```

The first arXiv pass ran on November 3, 2026. It found 668 unique arXiv papers cited by the inventory. 400 passed the include rules and were added as issues. 2 were already in the inventory. That run also opened duplicate issues after GitHub returned server errors, and it pushed the export straight to `master`. Use the commands below for later passes.

### File a batch

Install the checker once per environment:

```bash
python3 -m pip install -r scripts/requirements.txt
```

Write the screened papers to `work/queue.json`. The `work/` directory is gitignored.

```json
{
  "items": [
    {
      "title": "Paper title",
      "source": "Organization name",
      "url": "https://example.org/paper.pdf",
      "date_published": "March 2026",
      "summary": "One sentence from the paper."
    }
  ]
}
```

If you omit `wp_id`, the command reserves the next free id in the run file before it calls GitHub.

File up to 25 papers. On a long queue, set the batch size from 25 to 50.

```bash
python3 scripts/file_issues.py run --queue work/queue.json --batch-size 25
```

The command writes `runs/<UTC date>.json` and `runs/latest.txt`. Each item is `pending`, `issue_open`, `done`, or `already_filed`. At the top of the file, `done` and `pending` list WP- ids. `created_issues` maps a WP- id to the issue number the command opened.

Run the same command again, with or without `--queue`, to resume. When you omit `--date`, the command follows `runs/latest.txt`. Pass `--date YYYY-MM-DD` to select a run, including a run that was still pending after UTC midnight. If `latest.txt` points at a finished run and you pass a new queue, the command starts today's file.

`GITHUB_TOKEN` or `GH_TOKEN` must be able to open issues. `GITHUB_PROJECTS_TOKEN` must be able to add items to GitHub Project 2. The script reads those variables and does not print them. If you omit `GITHUB_PROJECTS_TOKEN`, the project step uses the issue token.

The script lists issue bodies and searches for `<!-- wp-id: WP-0000 -->` before it opens an issue. It does not use the Search API for that check, because search lags behind the issue list. After a 5xx response or a timeout, it lists again. It opens another issue only after that list finishes and the marker is still absent. Project adds use the same check.

See what is left:

```bash
python3 scripts/file_issues.py show
```

### Pull request

Rebuild the export from the issues:

```bash
python3 scripts/export_whitepapers.py
```

Check the schema and the WP- id rules on the machine:

```bash
python3 scripts/validate_whitepapers.py --schema-only
```

Put the export on a branch and open a pull request. Do not push to `master`.

```bash
git checkout -b weekly/2026-11-04
python3 scripts/open_inventory_pr.py
```

`scripts/open_inventory_pr.py` runs the schema check, commits `data/whitepapers.json`, `data/whitepapers.csv`, and `runs/`, pushes the current branch, and opens a pull request into `master`. It refuses `master` and `main`. It does not force-push. Wait until the GitHub check `validate-whitepapers` passes, then merge the pull request.

The check also reads the issues and compares them with the export. `--schema-only` does not do that read. CI does.

## Files

- `data/whitepapers.json` is the versioned inventory. `version` is the file format. `updated` is the date the file was written. `id_registry` lists every `WP-` id, the issue that received it, and the URL it belongs to. The registry keeps an id after a paper drops out of the issue list, so the id is not given to a different URL. The second extraction list is `invariants`. Older issue headings may say `### Invariables`; the export reads that heading into the same list.
- `data/whitepapers.csv` is the same papers in a spreadsheet, one row per paper, keyed by `WP-` id.
- `schemas/whitepapers.schema.json` is the contract for the JSON file.
- `scripts/export_whitepapers.py` writes the JSON and CSV files.
- `scripts/sync_issues.py` reads the issues and prints counts. It does not write files and it does not edit issues.
- `scripts/validate_whitepapers.py` is the check that CI runs. `--schema-only` is the local schema and WP- id check.
- `scripts/file_issues.py` opens one batch of issues and adds them to GitHub Project 2. It resumes from `runs/<date>.json`.
- `scripts/open_inventory_pr.py` commits the export on the current branch and opens a pull request. It does not push `master`.
- `runs/` holds the checkpoint for each weekly pass. `runs/latest.txt` names the date to resume.
- `AGENTS.md` lists the commands, the rules, and the known traps.
- `docs/extraction-handoff.md` explains how to extract Axioms, Invariants, Principles, and OpenCRE Topics from a paper into an issue.
- `scripts/requirements.txt` lists the packages the check installs.
- `data/` also holds paste files, watch lists, change logs and extraction notes from before October 31, 2026. Those files record the old sheet work. The live inventory is the issues and `data/whitepapers.json`.
- `scripts/sheet_sync.py` and `scripts/extraction.py` stop immediately. They used to read and write the sheet.

## Branch protection

The default branch in this repo is `master`. The weekly pass opens a pull request. It does not push to `master`. Protect `master` so a direct push cannot skip the check. A commit cannot turn that setting on. Set it in GitHub. If you later rename the default branch to `main`, use the same rules on `main`.

1. Open Settings, then Rules, then Rulesets. (A classic branch protection rule under Branches is the same idea.)
2. Add a ruleset that targets the default branch, `master`.
3. Require a pull request before merging.
4. Require the status check `validate-whitepapers` to pass before merging.
5. Do not allow administrators to bypass the rule, unless you have a written reason to keep a bypass.

## License

The license for this data is not set yet. This repo has no LICENSE file.

