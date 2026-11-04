# Agent notes

This repo is the AI security whitepaper inventory. GitHub issues are the source of truth. `data/whitepapers.json` and `data/whitepapers.csv` are the export built from those issues.

Read [README.md](README.md) for the issue format, the include rules, and the weekly pass. This file is the short list of commands, rules, and traps. To fill Axioms, Invariants, Principles, and OpenCRE Topics on an issue, follow [docs/extraction-handoff.md](docs/extraction-handoff.md).

## Commands

Install the schema checker once per environment:

```bash
python3 -m pip install -r scripts/requirements.txt
```

Check the JSON file against the schema and the WP- id rules. This does not call GitHub:

```bash
python3 scripts/validate_whitepapers.py --schema-only
```

Read issues and print counts. This does not write files and does not edit issues:

```bash
python3 scripts/sync_issues.py
```

Rebuild the export from issues:

```bash
python3 scripts/export_whitepapers.py
```

List included papers that have no evidence level. The default batch is 25. This reads the export and does not edit issues:

```bash
python3 scripts/missing_evidence.py
python3 scripts/missing_evidence.py --offset 25
```

File one batch from a screened queue. The default batch size is 25. Use a batch size from 25 to 50. The run file is `runs/<date>.json`. A second invocation resumes that file.

GitHub writes go through `scripts/gh_rate.py`: one request at a time, 1 second apart, 400 writes an hour. A batch of 25 is 50 writes (one issue create and one project add per paper). Exit code 2 means the hourly budget is spent and the run file is saved. Wait until the printed time, then run the same command. For a long backfill, use `--batch-size 50` and repeat after each budget stop. One filing command at a time. `GITHUB_WRITE_DELAY` (minimum 1) and `GITHUB_HOURLY_WRITE_BUDGET` (maximum 450) change the defaults.

```bash
python3 scripts/file_issues.py run --queue work/queue.json --batch-size 25
python3 scripts/file_issues.py show
```

Open a pull request for the export. Create the branch yourself. The command refuses `master` and `main`, and it does not force-push:

```bash
git checkout -b weekly/2026-11-04
python3 scripts/open_inventory_pr.py
```

The full GitHub check is `python3 scripts/validate_whitepapers.py`. CI runs that check under the name `validate-whitepapers`. Wait for it to pass before merging.

Publish included papers to the site repo. `SITE_REPO_TOKEN` must be able to open a pull request on `billbrietstout/ai-shared-responsibility`. The command does not print the token:

```bash
python3 scripts/site_inventory.py --out /tmp/site-inventory
python3 scripts/open_site_pr.py --from /tmp/site-inventory
```

## Rules

- `raw/` is read-only. Do not add, edit, or delete files under `raw/`.
- Do not close or delete GitHub issues. File a new issue only through `scripts/file_issues.py`. That command searches for the `<!-- wp-id: WP-0000 -->` marker first. It does not edit an issue that already exists.
- Do not print `GITHUB_PROJECTS_TOKEN`, `GITHUB_TOKEN`, or `GH_TOKEN`. Do not write them into the run file, the log, or a pull request body.
- Do not read or write the retired Google Sheet. `scripts/sheet_sync.py` and `scripts/extraction.py` exit on purpose.
- Data changes go through a pull request into `master`. Do not push to `master` or `main`. Do not force-push.
- Do not print `SITE_REPO_TOKEN`. Site inventory pull requests go to `billbrietstout/ai-shared-responsibility`. They do not rewrite the principle catalogs.

## Known traps

- A GitHub 403, 429, 5xx, timeout, or dropped connection can arrive after the issue was created. `scripts/gh_rate.py` waits on `Retry-After`, on `X-RateLimit-Reset` when remaining is 0, or for 60 seconds and then longer, and it lists issues for the `wp-id` marker before it creates again. The Search API lags behind the issue list. On November 3, 2026, retries opened a second issue for the same paper. The extra copies include the pairs #352 and #354, #353 and #355, #398 and #400, #399 and #401, #481 and #483, #482 and #484, #526 and #528, and #527 and #529. Do not close or edit those issues from a script.
- A long run gets cut off. `runs/<date>.json` is rewritten after each issue and each project add. Resume with the same `--date`, or omit `--date` and follow `runs/latest.txt`. If the checkpoint was lost, the marker search still finds an issue that was already opened.
- Project adds use the same check. Set `GITHUB_PROJECTS_TOKEN` in the environment for GitHub Project 2. The script reads it and does not print it.
- `jsonschema` is not part of the Python standard library. If the schema check fails on import, run the pip command above.
- The November 3, 2026 export was pushed straight to `master`. Later data changes use `scripts/open_inventory_pr.py`.
