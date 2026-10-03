# Extraction pass prompt

Paste this file into a Cursor agent chat, or say "run the extraction pass in docs/extraction-prompt.md". The agent fills `Axioms`, `Invariables`, `Principles`, and `OpenCRE Topics` on inventory rows where all four are empty. It never overwrites a filled cell.

## Setup (once)

```bash
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements-extraction.txt
```

The script signs in with a service account key that can edit the sheet. Save the key outside the repo at `~/.config/gspread/service_account.json` (`chmod 600`), or point `GOOGLE_APPLICATION_CREDENTIALS` at it. The monitor's service account works; its GitHub secret cannot be read back, so create a second key for the same account.

## Steps

1. Run `.venv/bin/python scripts/extraction.py worklist` (add `--limit N`, `--tab MOSAIC`, or `--link URL` to narrow the batch). It reads the sheet, downloads each row's Link, and writes `work/extraction/worklist.json` plus one text file per row under `work/extraction/texts/`.
2. For each worklist item that has a `text_file`, read the whole file. PDF text carries `[page N]` markers. Items with a `fetch_error` are skipped; the apply step logs them under Changelog Errors.
3. Screen the item against the include rules below. Then extract the four columns using the definitions below.
4. Write every result to `work/extraction/results.json` using the output format below.
5. Run `.venv/bin/python scripts/extraction.py apply`. This is a dry run. Fix each `FIX` line in `results.json` and rerun until it reports no problems.
6. Show the user the results for the first two items and wait for approval. Then run `.venv/bin/python scripts/extraction.py apply --write`.
7. Report how many rows were filled, which rows failed the include rules (the user deletes those), and any fetch errors.

## Include screen

Include a public, dated artifact whose main job is AI security: controls, threats, secure development, shared responsibility, verification, or agent and model security. Whitepapers, frameworks, profiles, playbooks, guides, cheat sheets, taxonomies, living documents, and standards qualify.

Exclude product marketing, model-launch blogs, trust-center copy, conference slides with no paper, news-only posts, and ethics or policy papers that name no security control, threat, or verification method.

A blog post that announces a paper fails the screen. Name the paper and its URL in `include_reason` so the user can add the paper as its own row. A blog post whose body is itself the guidance (for example, a set of controls with rationale) passes.

## Definitions

Each bullet names who does what, to which object, under what condition. Use concrete verbs: measure, assign, log, block, revoke, attest, map, require. Take every claim from the document. Do not add claims the document does not make.

**Axioms** are premises the document treats as true about AI systems, attackers, or adoption, which its guidance depends on. They describe the world outside the system being secured. They never describe the document itself ("the guide has three sections" is not an axiom). A statement that uses must, never, or shall is a requirement; put it under Invariables.

- Example: "Adversaries already use AI to attack faster than humans can respond."

**Invariables** are properties that hold for every system in the document's scope, whatever the deployment. The document states them either as requirements ("must", "never", "always") or as unavoidable facts about the system. Test: if the property fails, the document would call the system insecure or non-compliant regardless of its other controls.

- Requirement: "Every AI system must be documented and auditable."
- Unavoidable fact: "Any ML system that is not fully white-box is susceptible to model extraction."

**Principles** are guidance the document recommends, where the reader chooses how to apply it. Write each as `Name: actor, action, object, condition`. When the document uses a known named principle (least privilege, defense in depth, fail securely, complete mediation), keep that name so the bullet can be mapped to the principles catalog later. Otherwise use a short descriptive name.

- Example (hypothetical agent-tools guide): "Least privilege: the platform team grants each agent only the tools its current task requires and revokes them when the task ends."

**OpenCRE Topics** are 1 to 6 labels, chosen only from this list:

Access Control, Authentication, Cryptography, Data Protection, Governance-Risk-Compliance, Incident Response, Input Validation, Log Management, Secrets Management, Secure Product Design, Session Management, Supply Chain, Threat Modeling, Training and Awareness, Vulnerability Management.

Pick a label only when the document gives a control, threat, or requirement in that area. A passing mention does not count.

## Rules the apply step enforces

- 3 to 8 bullets each for Axioms, Invariables, and Principles; 240 characters or fewer per bullet.
- Every bullet has a `ref`: a page (`p. 12`), section title, or short quote locator.
- No em dashes or en dashes.
- None of these words: delve, dive into, unpack, leverage, harness, unlock, foster, empower, elevate, streamline, navigate, landscape, ecosystem, tapestry, realm, multifaceted, robust, seamless, cutting-edge, groundbreaking, holistic, comprehensive, end-to-end, pivotal, crucial, vital, underscore, highlight, showcase, illuminate, best practices, industry standards, ensure. Replace each with the concrete verb or object the sentence needs.
- Axioms contain no must, never, or shall.
- Every Principle contains a colon after its name.

## Output format

`work/extraction/results.json` is a JSON array with one object per worklist item that has text:

```json
[
  {
    "link": "https://example.org/paper.pdf",
    "include": true,
    "include_reason": "Framework of AI supply chain controls with rationale.",
    "axioms": [{"text": "...", "ref": "p. 3"}],
    "invariables": [{"text": "...", "ref": "p. 7"}],
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

`link` must match the worklist item's link. Items with `include: false` need only `link`, `include`, and `include_reason`.

The `ref` values stay out of the sheet. The write step saves them with the bullets in `data/extraction-evidence-YYYY-MM-DD.json` so each bullet can be checked against the source.
