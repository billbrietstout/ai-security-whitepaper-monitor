# Sunday inventory refresh

Source of truth: [MOSAIC_AI_Security_Whitepapers](https://docs.google.com/spreadsheets/d/161FFOVjQUNxiaOzMryT6sbEuYjq-uLf-vcDEHfvlFbE/edit). This file is the runbook for the weekly Sunday job and for a manual "refresh the inventory" chat.

## Tabs

Inventory tabs, in this order. The tab is the group. Do not put the same paper on two inventory tabs.

1. `MOSAIC` — BIML, CIS, CSA, CoSAI, NIST, OWASP AI Exchange, OWASP GenAI Security Project, SANS. Issuer column is `MOSAIC Member`.
2. `Peer SDOs` — MITRE, ETSI, ENISA, ISO/IEC, IEEE, OASIS, ITU, and similar. Issuer column is `Organization`.
3. `Government` — CISA, NCSC, CAISI, UK AISI, BSI, ANSSI, SEI/CERT, and similar. Issuer column is `Organization`.
4. `Coalitions` — OpenSSF, MLCommons, Frontier Model Forum, Partnership on AI, AI Verify, and similar. Issuer column is `Organization`.
5. `Vendor labs` — Google, Microsoft, OpenAI, Anthropic, Meta, AWS, and similar. Issuer column is `Organization`.
6. `Watch list` — catalog URLs to re-check.
7. `Changelog` — one row per run.

`#` restarts at 1 on each inventory tab.

Joint publications go on one tab only, the primary issuer’s group. CISA/NCSC joint guides go on `Government`. MITRE ATLAS stays on `Peer SDOs`. CoSAI stays on `MOSAIC`. NIST AI RMF and playbook stay on `MOSAIC`. Later CAISI-only papers go on `Government`.

If MOSAIC later onboard a body that already has rows on another tab, move those rows to `MOSAIC` and do not keep a duplicate.

## Inventory columns

`#`, issuer (`MOSAIC Member` or `Organization`), `Publication`, `Date Published`, `Category`, `File Type`, `Link`, `Axioms`, `Invariables`, `Principles`, `OpenCRE Topics`, `Blog / Announcement`.

Watch list: Organization, Tab, Catalog URL, Last checked, Notes.

Changelog: Date, Trigger (`Sunday job`, `manual`, or `GitHub monitor`), Orgs checked, Added, Updated, Skipped, Errors.

## What counts as a row

Include a public, dated artifact whose main job is AI security: controls, threats, secure development, shared responsibility, verification, or agent/model security. Formats already in the sheet stay valid: whitepaper, framework, profile, playbook, guide, cheat sheet, taxonomy, living document, standard.

Exclude product marketing, model-launch blogs, trust-center copy, conference slides with no paper, news-only posts, and ethics or policy papers that name no security control, threat, or verification method.

Paywalled ISO/IEC (42001, 23894, 27090, and similar): bibliographic row plus axioms/principles taken only from official public abstracts, previews, or the issuer’s own summary. Do not reconstruct standard body text.

Vendor labs: include only standalone public guidance. Skip product docs and model cards.

Treat a revision as an update to the existing row when it is the same named work (CSA AICM 1.0 to 1.1). Add a new row when the name, scope, or series changes (OWASP LLM Top 10 2023 vs 2026).

## Extraction style

Read the paper or official public summary. Fill `Axioms`, `Invariables`, and `Principles` as short bullets that name who does what, to which object, under what condition. Use concrete verbs: measure, assign, log, block, revoke, attest, map, require.

[extraction-prompt.md](extraction-prompt.md) holds the definitions that separate the three columns, the allowed `OpenCRE Topics` labels, and the checks each bullet must pass. In short: Axioms are premises about the world outside the system; Invariables are properties that hold for every in-scope system, stated as requirements or as unavoidable facts; Principles are recommended guidance written as `Name: actor, action, object, condition`. `OpenCRE Topics` use the 15 base labels the sheet already uses most, starting with Access Control, Secure Product Design, Threat Modeling, Data Protection, and Supply Chain.

To fill rows with empty extraction columns, run the Cursor extraction pass in that file.

Keep `Category` and `File Type` in the vocabularies already used (`Framework`, `Whitepaper`, `Guide`, `PDF`, `Web`, and so on). Do not invent a new category unless none of the existing ones fit.

A row may go on an inventory tab with Axioms, Invariables, Principles, or OpenCRE Topics empty. Fill those columns on a later pass. If extraction fails, write the row with the extraction columns empty and name the paper under Changelog Errors so the next run retries it.

## Sunday job steps

Schedule: every Sunday at 09:00 Pacific.

1. Read `Watch list` and every inventory tab.
2. Open each Catalog URL. Diff titles, dates, and version strings against rows already on the named tab.
3. For each new or revised paper that passes the include rules: write the row onto the correct group tab (or update the same-name row), then read the paper and fill the extraction columns. Rows with empty extraction columns from earlier runs are retried in this step.
4. Set `Last checked` on every Watch list row actually opened, including no-change rows.
5. Append one Changelog row. If papers were added or updated, name them in Added / Updated.

Do not invent papers that are not on a catalog page. Do not duplicate a paper across tabs.

If the run cannot write the spreadsheet, record what was found in Changelog Errors or the automation run log. Do not claim the inventory was updated.

## Writing to the sheet

Write changes with `scripts/sheet_sync.py`, not paste files. Put every change for the run in `work/<run>/plan.json` (operations: update, replace, append, delete; see the script docstring). Then:

1. `.venv/bin/python scripts/sheet_sync.py work/<run>/plan.json` prints the dry run. Nothing is written.
2. Show the dry run to the user and wait for approval.
3. `.venv/bin/python scripts/sheet_sync.py work/<run>/plan.json --write` applies it and rereads every written cell.

The script finds rows by column values (`#`, Organization, Publication, Link), never by sheet row number. It writes values as plain text, so dates stay as written. It refuses an append whose Link sits on another inventory tab, and it stops the whole plan if any match is missing or ambiguous. Rerunning a plan is safe; finished operations count as already done.

## GitHub monitor

The GitHub Action in `billbrietstout/cosai-mosaic-monitor` runs every Monday at 09:00 UTC. It reads the CoSAI resources page, CoSAI GitHub releases, and the news feeds of OWASP GenAI, SANS, CSA, CIS, BIML, and CoSAI. News items are kept only when the title names AI, LLMs, agents, MCP, or a similar term.

Each new link that is not on any inventory tab is appended to `MOSAIC` with `#`, `MOSAIC Member`, `Publication`, `Date Published`, `File Type`, and `Link` filled. News and blog posts get Category `Article`. PDFs and GitHub releases leave Category empty. The extraction columns stay empty. The run appends one Changelog row with Trigger `GitHub monitor` and lists the new rows under Added.

The monitor does not apply the include rules above, so it writes news posts and press releases those rules exclude. On review, delete rows that fail the include rules, and fill Category and the extraction columns on the rest. A deleted row stays deleted on scheduled runs, because the monitor's own `inventory/documents.csv` already lists the link. A manual run with `backfill_since` set rewrites deleted rows added to that CSV on or after the date.

The `Monitor queue` tab is retired. While it exists, links marked there with any Review status other than `New` stay off the inventory.
