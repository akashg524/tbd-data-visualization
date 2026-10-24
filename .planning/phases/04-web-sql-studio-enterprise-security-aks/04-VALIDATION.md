---
phase: 4
slug: web-sql-studio-enterprise-security-aks
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-10-24
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Backend Framework** | pytest 8.4+ with pytest-asyncio |
| **Frontend Framework** | TypeScript 6.0 + Vite 8.3 + React 19 |
| **Quick Backend Command** | `.\.venv\Scripts\pytest.exe tests/ -q` |
| **Full Backend Command** | `.\.venv\Scripts\pytest.exe tests/ -v` |
| **Frontend Build Command** | `cd frontend; npm run build` |
| **Frontend Lint Command** | `cd frontend; npm run lint` |
| **Helm Lint Command** | `helm lint deploy/helm/data-hub` |

---

## Sampling Rate

- **After every task commit:** Run quick backend command or frontend build
- **After every plan wave:** Run full test suite & frontend build
- **Before `/gsd-verify-work`:** All suites must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | REQ-13 | Monaco SQL Editor & Catalog Intellisense | unit / build | `npm run build` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | REQ-13 | Results Grid & Explain Plan Timeline | component | `npm run build` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 2 | REQ-14 | Entra ID JWT verification & Role enforcement | unit / integration | `pytest tests/test_auth.py -v` | ❌ W0 | ⬜ pending |
| 04-03-01 | 03 | 3 | REQ-15 | Multi-stage Dockerfiles & Helm packaging | lint / build | `helm lint deploy/helm/data-hub` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
