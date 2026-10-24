---
phase: 2
slug: federated-query-planner
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-10-24
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4+ with pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.\.venv\Scripts\pytest.exe tests/ -q` |
| **Full suite command** | `.\.venv\Scripts\pytest.exe tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | REQ-06 | Parse multi-source table aliases | unit | `pytest tests/test_sql_parser.py -v` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | REQ-07 | Isolate predicates per source | unit | `pytest tests/test_pushdown_compiler.py -v` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | REQ-08 | Zero-copy Arrow hash join | integration | `pytest tests/test_federated_executor.py -k join -v` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | REQ-09 | End-to-end multi-store streaming | integration | `pytest tests/test_federated_executor.py -k stream -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
