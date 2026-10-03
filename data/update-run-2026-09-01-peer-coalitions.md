# Watch list refresh — Peer SDOs + Coalitions (12 orgs)

**Date:** 2026-09-01  
**Trigger:** manual  
**Baseline:** Peer SDOs and Coalitions inventory tabs empty (headers only). No row-level diff possible.

## Summary

| Result | Count |
|--------|------:|
| Orgs checked | 12 |
| Same-day catalog update | 1 (MITRE ATLAS v2026.08) |
| Qualifying papers queued for first inventory pass | ~28 |
| Catalog URL / access errors | 3 |
| Skipped (news, testimony, courses, ethics-only) | several per org |

## Per-org results

### Peer SDOs

| Organization | Status | Findings |
|--------------|--------|----------|
| **MITRE** | **Update** | ATLAS content **v2026.08** published **2026-09-01** (114 techniques, agentic additions: AML.T0116–T0128, tactic rename AI Attack Adaptation). Living taxonomy at https://atlas.mitre.org/ ; releases at https://github.com/mitre-atlas/atlas-data/releases |
| **ETSI** | New inventory | **EN 304 223** V2.1.1 (2025-12; announced 2026-01-14). Also **TS 104 008** CABCA (2026-01-27), Securing AI Computing Platforms press (2026-06-02). SAI TC: https://www.etsi.org/committee/1947 |
| **ENISA** | New inventory | **Cybersecurity in the Frontier AI Era** (2026-07-07). Prior: Mind the Gap (2023), Is Secure and Trusted AI Possible? (2023), AI and Cybersecurity Research (2023), Cyber Insurance + AI (2024) |
| **ISO/IEC JTC 1/SC 42** | Blocked | Committee page blocked automated fetch (Cloudflare). Queue bibliographic rows from public summaries: ISO/IEC 42001, 23894, 27090 |
| **IEEE** | **Catalog error** | Watch URL returns **404**. No fetch this run |
| **OASIS Open** | No new OASIS-only paper | Projects archive lists CoSAI (already on **MOSAIC** tab). No separate OASIS-native AI security whitepaper identified beyond CoSAI |
| **ITU-T** | Catalog mismatch | Watch URL serves **AI for Good** hub, not ITU-T deliverables list. Security-adjacent pubs: Multimedia Authenticity technical paper (2nd ed), AI Ready readiness framework |

### Coalitions

| Organization | Status | Findings |
|--------------|--------|----------|
| **OpenSSF** | New inventory | Published **Security-Focused Guide for AI Code Assistant Instructions** (2025-08-01). Active specs/WGs: Model Signing, SAFE-MCP (MCP agent security), E2E Model Provenance. Org landing page sparse; use https://github.com/ossf/ai-ml-security |
| **MLCommons** | No dated whitepaper on catalog | **AI Risk & Reliability** WG listed; no standalone security guidance PDF on working-groups page. Track for benchmark releases |
| **Frontier Model Forum** | New inventory | **Publications** page (better watch URL than `/updates/`): 2026 security items include *Emerging Security Practices for AI Agents* (2026-06-03), *Managing Advanced Cyber Risks in Frontier AI Frameworks* (2026-02-13), *Information Sharing…* brief (2026-05-12). `/updates/` is news only |
| **Partnership on AI** | New inventory | Safety-Critical AI program: *Guidance for Safe Foundation Model Deployment* (2023-10-24), *Risk Mitigation Strategies for the Open Foundation Model Value Chain* (2024-07-11), *Prioritizing Real-Time Failure Detection in AI Agents* (2025-09-11). `/work/` is program overview only |
| **AI Verify Foundation** | New inventory | *Model Governance Framework for Agentic AI* (updated **2026-05**), *Starter Kit for Testing LLM-based Applications*, *Catalogue of LLM Evaluations* (draft), *Model AI Governance Framework for Generative AI*, AI Verify toolkit + ISO 42001 / NIST RMF crosswalks |

## Recommended watch URL fixes

| Organization | Current | Suggested |
|--------------|---------|-----------|
| IEEE | `…/artificial-intelligence-systems/` (404) | `https://standards.ieee.org/industry-connections/ai-systems/` or IEEE SA AI landing |
| OpenSSF | `openssf.org/groups/ai-ml-security/` (empty) | `https://github.com/ossf/ai-ml-security` |
| Frontier Model Forum | `…/updates/` | `https://www.frontiermodelforum.org/publications/` |
| ITU-T | AI for Good page | `https://www.itu.int/hub/itu-publications/` + AI Standards Exchange filter |
| ETSI | AI technologies landing | Add SAI TC deliverables: `https://www.etsi.org/committee/1947` |

## Changelog row (when sheet is updated)

```
2026-09-01	manual	12 Peer SDO/Coalition (Watch list)	none (Peer SDOs + Coalitions tabs empty)	MITRE ATLAS v2026.08	IEEE catalog 404; ISO fetch blocked
```

## Next steps

1. Fix watch list Catalog URLs on sheet (table above).
2. Set **Last checked** = 2026-09-01 for all 12 rows (already seeded date).
3. Extract and paste flagship rows first: MITRE ATLAS, ETSI EN 304 223, ENISA Frontier AI, OpenSSF AI Code Assistant Guide, FMF Emerging Security Practices for AI Agents, PAI Safe Foundation Model Deployment, AI Verify Agentic AI MGF.
4. Full queue: see `docs/pending-inventory-rows.md`.
