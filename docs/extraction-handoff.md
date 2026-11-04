# Handoff: extracting axioms, invariants, principles, and OpenCRE topics

This note is for the next agent or person who fills the four extraction fields on an inventory paper. The inventory lives in GitHub issues in this repo. `data/whitepapers.json` is rebuilt from those issues. The writing rules below match [extraction-prompt.md](extraction-prompt.md). That file is the check list. It does not tell you to run the retired sheet command.

The second field is **Invariants**. Older issues, and the retired sheet, use **Invariables**. The export reads both headings into `invariants` and does not write a second key. A new issue heading is `### Invariants`. Leave an existing `### Invariables` heading in place, or rename it when you edit that section.

## Where the fields live

Each paper issue has four markdown sections:

```markdown
### Axioms
- ...

### Invariants
- ...

### Principles
- Name: actor, action, object, condition

### OpenCRE Topics
- Supply Chain
```

`scripts/file_issues.py` opens a new issue with those four headings set to `_Not filled yet._`. The second heading on a new issue is `### Invariants`. The filing command does not extract text from the paper, and it does not edit an issue that already exists.

`scripts/inventory.py` reads the four headings when it builds the export. `_Not filled yet._`, `Not extracted yet.`, and `Not extracted yet. The next pass will fill this from the paper.` become an empty list. A real bullet is a line that starts with `- `. A wrapped line with no dash continues the bullet above it. A line with no dash and no bullet above it is left out. If an issue has both `### Invariables` and `### Invariants`, both sets of bullets are kept. The export stores `axioms`, `invariants`, `principles`, and `opencre_topics`.

The Google Sheet and `scripts/extraction.py` are retired. Do not run them.

## When to extract

Extract when you edit an open issue by hand and the four sections are empty or still say `_Not filled yet._`. Screen the paper first with the include rules in [README.md](../README.md) and [extraction-prompt.md](extraction-prompt.md). Skip extraction when the paper fails the screen; close that issue as a delete candidate instead.

Paywalled standards: take claims only from official public abstracts, previews, or the issuer's own summary. Do not reconstruct closed body text.

## Read the paper first

1. Open the URL on the issue's `**Link:**` line.
2. Read the full text when you can. For a PDF, keep page numbers. For HTML, keep section titles.
3. Take every claim from the document. Do not add claims the document does not make.
4. Each bullet should name who does what, to which object, under what condition. Prefer concrete verbs: measure, assign, log, block, revoke, attest, map, require.

Keep a short locator for each bullet while you draft (`p. 12`, a section title, or a short quote). Locators help you check your work. They do not go into the issue body. If you need to keep them for later review, write them next to the bullets in a local file under `work/` (gitignored). Older sheet runs stored locators in `data/extraction-evidence-YYYY-MM-DD.json`.

## How the four fields differ

### Axioms

Premises the document treats as true about AI systems, attackers, or adoption. The guidance depends on them. They describe the world outside the system being secured.

- They are not requirements. Do not use must, never, or shall.
- They never describe the document itself. "The guide has three sections" is not an axiom.
- Example: `Adversaries already use AI to attack faster than humans can respond.`

### Invariants

Properties that hold for every system in the document's scope, whatever the deployment. The document states them as requirements (`must`, `never`, `always`) or as unavoidable facts about the system.

Test: if the property fails, the document would call the system insecure or non-compliant even when its other controls are present.

- Requirement example: `Every AI system must be documented and auditable.`
- Unavoidable-fact example: `Any ML system that is not fully white-box is susceptible to model extraction.`

If a sentence uses must, never, or shall, it belongs here, not under Axioms.

### Principles

Guidance the document recommends, where the reader chooses how to apply it. Write each as:

`Name: actor, action, object, condition`

When the document uses a known named principle (least privilege, defense in depth, fail securely, complete mediation), keep that name so the bullet can later map to a principles catalog. Otherwise use a short descriptive name.

Example: `Least privilege: the platform team grants each agent only the tools its current task requires and revokes them when the task ends.`

### OpenCRE Topics

One to six labels. Choose only from this closed list:

Access Control, Authentication, Cryptography, Data Protection, Governance-Risk-Compliance, Incident Response, Input Validation, Log Management, Secrets Management, Secure Product Design, Session Management, Supply Chain, Threat Modeling, Training and Awareness, Vulnerability Management.

Pick a label only when the document gives a control, threat, or requirement in that area. A passing mention does not count. Put one label per bullet line.

## Sorting a borderline sentence

| Question | Field |
| --- | --- |
| Is this a premise about the outside world that the paper assumes? | Axiom |
| Would a miss make every in-scope system fail, as a hard requirement or unavoidable fact? | Invariant |
| Is this advice the reader applies by choice, with an actor and an action? | Principle |
| Is this only a topic tag for later OpenCRE mapping? | OpenCRE Topics |

Do not invent a principle that the paper never recommends. Do not promote a topic mention into a principle.

## Writing rules every bullet must pass

- Axioms, Invariants, and Principles: 3 to 8 bullets each, 240 characters or fewer per bullet.
- OpenCRE Topics: 1 to 6 labels from the list above.
- No em dashes or en dashes.
- Do not use these words: delve, dive into, unpack, leverage, harness, unlock, foster, empower, elevate, streamline, navigate, landscape, ecosystem, tapestry, realm, multifaceted, robust, seamless, cutting-edge, groundbreaking, holistic, comprehensive, end-to-end, pivotal, crucial, vital, underscore, highlight, showcase, illuminate, best practices, industry standards, ensure. Replace each with the concrete verb or object the sentence needs.
- Axioms contain no must, never, or shall.
- Every Principle has a colon after its name.

The old sheet apply step enforced those checks in code. On issues, you enforce them by hand before you save the edit. When you draft in `work/extraction/results.json` style first, keep the same shape as [extraction-prompt.md](extraction-prompt.md) and check the counts and banned words yourself.

## Put the result on the issue

Replace `_Not filled yet._` under each heading with real bullets. Example:

```markdown
### Axioms
- Adversaries already use AI to attack faster than humans can respond.

### Invariants
- Every AI system must be documented and auditable.

### Principles
- Least privilege: the platform team grants each agent only the tools its current task requires and revokes them when the task ends.

### OpenCRE Topics
- Access Control
- Supply Chain
```

Do not put page refs in the issue body. Do not change `**Source:**` or `**Link:**` unless the paper URL itself changed. Do not close or delete an issue from a script. After the issue edit, rebuild the export on a branch and open a pull request:

```bash
git checkout -b extract/wp-NNNN
python3 scripts/export_whitepapers.py
python3 scripts/open_inventory_pr.py
```

Check out the branch before the export. The export writes the files in the working tree, and `open_inventory_pr.py` refuses to commit them on `master`.

Wait for the `validate-whitepapers` check, then merge.

## What stays empty on purpose

A new issue may ship with empty extraction sections. That is allowed. Fill them on a later pass. Weekly filing of screened papers does not require extraction in the same batch.

## Related files

- [extraction-prompt.md](extraction-prompt.md): full definitions, banned-word list, and the old JSON draft format.
- [README.md](../README.md): issue format, include rules, weekly pass, export and PR steps.
- [AGENTS.md](../AGENTS.md): short command list and traps.
- `scripts/inventory.py`: parses the four `###` sections into the export.
- `scripts/filing.py`: writes the `_Not filled yet._` placeholders on new issues.
- `schemas/whitepapers.schema.json`: each paper must have the four arrays (empty arrays are valid). The second array is `invariants`.
