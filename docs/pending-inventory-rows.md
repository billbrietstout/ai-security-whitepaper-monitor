# Pending inventory rows (subagent run blocked)

The Google Sheet was retired on October 31, 2026. GitHub issues are the source of truth. Do not paste the rows below into the sheet. See [README.md](../README.md). The rest of this file is a record of a blocked research run.

Four parallel research runs failed on **2026-08-31** before returning paste-ready rows:

| Run | Agent | Error |
|-----|-------|-------|
| MOSAIC catalog diff | [Find missing MOSAIC papers](31ac216e-b01b-4970-9720-feb5c81d3ae2) | Usage limit |
| Peer SDOs | [Research peer SDO papers](0e1dfdc4-f31d-414d-b954-ec586e027a0d) | Usage limit |
| Government | [Research gov institute papers](4e13ca6f-4a18-4ac8-b1be-a7bbd1f5b165) | Unpaid invoice |
| Coalitions + vendor labs | [Research coalition and vendor papers](4a45495c-f44f-42b4-86fa-0cd98278b5f0) | Unpaid invoice |

Resolve at [cursor.com/dashboard](https://cursor.com/dashboard) (pay invoice or raise usage limits), then retry research or ask for a manual refresh in chat.

## Manual update run — 2026-08-31

Catalog diff: no new MOSAIC papers beyond #42–48 already on sheet. Watch list dates already `2026-08-31`.

**Still paste into sheet** (browser automation blocked mid-run):

| Fix | Action | File |
|-----|--------|------|
| Fix | Action | File |
|-----|--------|------|
| CoSAI links 14–20 rotated | Link column **G**, row with `#` 14 (G15 in snapshot); paste 7 URLs | `data/mosaic-cosai-links-fix-col-G.tsv` |
| #41 CoSAI SRF | **A41** full row (not A42) | `data/cosai-srf-row41.tsv` |
| #39 SANS v1.4 | **C39** cols C–L | `data/sans-v1.4-row39-cols-CL.tsv` |
| Government + Vendor labs tabs | add tabs, row 1 headers | `data/inventory-tab-headers.tsv` |
| Changelog row 2 | **A2** | `data/changelog-manual-2026-08-31.csv` |

Details: `data/update-run-2026-08-31.md`


## Other tabs — not researched

- **Peer SDOs** — priority-1 rows ready: `data/peer-sdos-priority1.tsv` (3 rows). Paste at **A2**.
- **Government** — fetch started; no final row list
- **Coalitions** — priority-1 rows ready: `data/coalitions-priority1.tsv` (5 rows). Paste at **A2**.
- **Vendor labs** — fetch started; no final row list

### Peer SDOs — extraction queue (2026-09-01)

| Priority | Publication | Date | Link |
|----------|-------------|------|------|
| 1 | MITRE ATLAS (living taxonomy; track v2026.08) | 2026-09-01 | https://atlas.mitre.org/ |
| 1 | ETSI EN 304 223 V2.1.1 | December 2025 | https://www.etsi.org/deliver/etsi_en/304200_304299/304223/02.01.01_60/en_304223v020101p.pdf |
| 1 | ENISA's view on Cybersecurity in the Frontier AI Era | July 2026 | https://www.enisa.europa.eu/publications/enisas-view-on-cybersecurity-in-the-frontier-ai-era |
| 2 | ETSI TS 104 008 (CABCA) | January 2026 | ETSI SAI deliverables |
| 2 | ENISA Mind the Gap in Standardisation of Cybersecurity for AI | 2023 | ENISA publications |
| 2 | ISO/IEC 42001 (public summary row) | 2023 | ISO committee 6793475 |
| 2 | ITU Multimedia Authenticity technical paper (2nd ed) | 2025–2026 | ITU AI for Good publications |

### Coalitions — extraction queue (2026-09-01)

| Priority | Publication | Date | Link |
|----------|-------------|------|------|
| 1 | OpenSSF Security-Focused Guide for AI Code Assistant Instructions | August 2025 | https://best.openssf.org/Security-Focused-Guide-for-AI-Code-Assistant-Instructions |
| 1 | FMF Emerging Security Practices for AI Agents | June 2026 | https://www.frontiermodelforum.org/issue-briefs/emerging-security-practices-for-ai-agents/ |
| 1 | FMF Managing Advanced Cyber Risks in Frontier AI Frameworks | February 2026 | https://www.frontiermodelforum.org/publications/ |
| 1 | PAI Guidance for Safe Foundation Model Deployment | October 2023 | partnershiponai.org (Safety-Critical AI) |
| 1 | AI Verify Model Governance Framework for Agentic AI | May 2026 | https://aiverifyfoundation.sg/resources/ |
| 2 | PAI Risk Mitigation Strategies for Open Foundation Model Value Chain | July 2024 | partnershiponai.org |
| 2 | PAI Prioritizing Real-Time Failure Detection in AI Agents | September 2025 | partnershiponai.org |
| 2 | AI Verify Starter Kit for Testing LLM-based Applications | — | aiverifyfoundation.sg |
| 2 | AI Verify Catalogue of LLM Evaluations (draft) | — | aiverifyfoundation.sg |
| 2 | OpenSSF SAFE-MCP (when published as spec) | in progress | GitHub ossf/ai-ml-security |

Follow [refresh-runbook.md](refresh-runbook.md) when writing rows onto the correct group tab and filling their extraction columns.
