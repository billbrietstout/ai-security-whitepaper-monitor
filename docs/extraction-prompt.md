# Extraction pass prompt

The Google Sheet was retired on October 31, 2026. GitHub issues are the source of truth. Do not run `scripts/extraction.py` against the sheet. That command now exits without reading or writing the sheet. The current update process is in [README.md](../README.md). The definitions below remain the writing rules for axiom, invariant, and principle bullets. The issue heading is `### Invariants`. Older issues and the retired sheet used `Invariables`. The export reads both headings.

This file used to be pasted into a Cursor agent chat so the agent could fill `Axioms`, `Invariants`, `Principles`, and `OpenCRE Topics` on sheet rows where all four were empty. The retired sheet header for the second column was `Invariables`.

## Steps

Do not run `scripts/extraction.py`. It exits without reading a paper.

1. Open the issue. Read the URL on the `**Link:**` line. Read the full text when you can. For a PDF, keep page numbers. For HTML, keep section titles.
2. Screen the paper with the include rules below. If it fails, do not extract. Close the issue and add these lines:

```
**Decision:** Delete candidate
**Reason:** one sentence on why it is out
```

A closed issue with no Decision line stops the export.

3. Extract when the four sections are missing, empty, or hold only an unfilled marker. The markers are `_Not filled yet._`, `Not extracted yet.`, and `Not extracted yet. The next pass will fill this from the paper.` The November 3, 2026 arXiv issues use the last two, with no leading dash.
4. Replace each unfilled marker with real bullets. Each bullet is its own line and starts with `- `. A wrapped line with no dash continues the bullet above it. A line with no dash and no bullet above it is left out of the export. The heading for the second field is `### Invariants`. Leave an existing `### Invariables` heading in place, or rename that heading when you edit the section.
5. Keep `**Source:**`, `**Link:**`, and any `### arXiv reference` section. Do not put page refs in the issue body. Locators can live in a local file under `work/` (gitignored).
6. Set an evidence level on every included paper. Delete candidates and duplicates do not need one. Judge the level from what the work did, not from the abstract alone. An organization guidance document that describes controls and reports no experiments is `theoretical`, unless it reports tested or deployed practice.
7. Check the writing rules below yourself. Nothing in the export enforces them.
8. Rebuild the export on a branch and open a pull request. Do not push to `master`.

```bash
git checkout -b weekly/2026-11-04
python3 scripts/export_whitepapers.py
python3 scripts/open_inventory_pr.py
```

Wait for the `validate-whitepapers` check, then merge. The filing command does not edit an issue that already exists, and it does not close an issue.

## Include screen

Include a public, dated artifact whose main job is AI security: controls, threats, secure development, shared responsibility, verification, or agent and model security. Whitepapers, frameworks, profiles, playbooks, guides, cheat sheets, taxonomies, living documents, and standards qualify.

Exclude product marketing, model-launch blogs, trust-center copy, conference slides with no paper, news-only posts, and ethics or policy papers that name no security control, threat, or verification method.

A blog post that announces a paper fails the screen. Name the paper and its URL in the Reason line so it can be filed as its own issue. A blog post whose body is itself the guidance (for example, a set of controls with rationale) passes.

## Evidence level

Every included paper needs one level. Write it as a bullet the export already copies into `legacy_notes`.

On an arXiv issue, add the line under `### arXiv reference`:

```
- Evidence level: tested
```

On any other included issue, add a section:

```
### Evidence
- Evidence level: theoretical
```

Use one of these four:

- `theoretical` means the work argues, surveys, or proposes. It reports no new experiments and no results from a real deployment.
- `tested` means the work ran experiments or evaluations.
- `tested, possibly deployed (needs review)` means the work ran experiments, and the text also uses deployment or production words that a person has not confirmed.
- `deployed` means the work tested real deployed systems or reports results from production.

Read the paper, not only the abstract. A guidance document from an organization, such as a whitepaper, framework, profile, playbook, or guide, is `theoretical` when it does not report experiments, unless the document itself reports tested or deployed practice.

A line that already says `provisional` or `needs review` is still a tag. It came from an automated read and still needs a person to confirm it.

To list included papers that have no tag, in batches of 25:

```bash
python3 scripts/missing_evidence.py
python3 scripts/missing_evidence.py --offset 25
```

The command reads `data/whitepapers.json`. It does not edit issues. Rebuild the export after you add lines, or the list still shows the old file.

## Definitions

Each bullet names who does what, to which object, under what condition. Use concrete verbs: measure, assign, log, block, revoke, attest, map, require. Take every claim from the document. Do not add claims the document does not make.

**Axioms** are premises the document treats as true about AI systems, attackers, or adoption, which its guidance depends on. They describe the world outside the system being secured. They never describe the document itself ("the guide has three sections" is not an axiom). A statement that uses must, never, or shall is a requirement; put it under Invariants.

- Example: "Adversaries already use AI to attack faster than humans can respond."

**Invariants** are properties that hold for every system in the document's scope, whatever the deployment. The document states them either as requirements ("must", "never", "always") or as unavoidable facts about the system. Test: if the property fails, the document would call the system insecure or non-compliant regardless of its other controls.

- Requirement: "Every AI system must be documented and auditable."
- Unavoidable fact: "Any ML system that is not fully white-box is susceptible to model extraction."

**Principles** are guidance the document recommends, where the reader chooses how to apply it. Write each as `Name: actor, action, object, condition`. When the document uses a known named principle (least privilege, defense in depth, fail securely, complete mediation), keep that name so the bullet can be mapped to the principles catalog later. Otherwise use a short descriptive name.

- Example (hypothetical agent-tools guide): "Least privilege: the platform team grants each agent only the tools its current task requires and revokes them when the task ends."

**OpenCRE Topics** are 1 to 6 labels, chosen only from this list:

Access Control, Authentication, Cryptography, Data Protection, Governance-Risk-Compliance, Incident Response, Input Validation, Log Management, Secrets Management, Secure Product Design, Session Management, Supply Chain, Threat Modeling, Training and Awareness, Vulnerability Management.

Pick a label only when the document gives a control, threat, or requirement in that area. A passing mention does not count.

## Writing rules

Check these by hand before you save the issue. The old sheet apply step enforced them in code. That command is retired.

- 3 to 8 bullets each for Axioms, Invariants, and Principles; 240 characters or fewer per bullet.
- Keep a locator for each bullet while you draft: a page (`p. 12`), a section title, or a short quote. The locator stays out of the issue.
- No em dashes or en dashes.
- None of these words: delve, dive into, unpack, leverage, harness, unlock, foster, empower, elevate, streamline, navigate, landscape, ecosystem, tapestry, realm, multifaceted, robust, seamless, cutting-edge, groundbreaking, holistic, comprehensive, end-to-end, pivotal, crucial, vital, underscore, highlight, showcase, illuminate, best practices, industry standards, ensure. Replace each with the concrete verb or object the sentence needs.
- Axioms contain no must, never, or shall.
- Every Principle contains a colon after its name.

## Optional local draft

You can draft in `work/extraction/results.json` before you edit the issue. That file is gitignored. Nothing in this repo checks it. One object per paper:

```json
[
  {
    "link": "https://example.org/paper.pdf",
    "include": true,
    "include_reason": "Framework of AI supply chain controls with rationale.",
    "axioms": [{"text": "...", "ref": "p. 3"}],
    "invariants": [{"text": "...", "ref": "p. 7"}],
    "principles": [{"text": "Least privilege: ...", "ref": "section 4.2"}],
    "opencre_topics": ["Supply Chain", "Access Control"]
  },
  {
    "link": "https://example.org/news/announcement",
    "include": false,
    "include_reason": "News post announcing the paper at https://example.org/paper.pdf; add the paper as its own row."
  }
]
```

Items with `include: false` need only `link`, `include`, and `include_reason`. Copy the bullet text into the issue. Leave the `ref` values in the local file.
