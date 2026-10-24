---
phase: 3
slug: speed-layer-semantic-power-bi-serving
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-10-24
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4+ with pytest-asyncio |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.\.venv\Scripts\pytest.exe tests/ -q` |
| **Full suite command** | `.\.venv\Scripts\pytest.exe tests/ -v` |
| **Estimated runtime** | ~8 seconds |

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
| 03-01-01 | 01 | 1 | REQ-10 | Pre-materialize dimension cache in memory | unit | `pytest tests/test_dimension_cache.py -v` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | REQ-12 | OData v4 feeds and RESTful views | integration | `pytest tests/test_odata_api.py -v` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | REQ-11 | PostgreSQL Wire Server accepts TCP connections | integration | `pytest tests/test_pgwire_server.py -v` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | REQ-11 | Power BI DirectQuery DAX query execution | integration | `pytest tests/test_pgwire_server.py -k directquery -v` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 3 | REQ-12 | Arrow Flight server gRPC stream transfer | integration | `pytest tests/test_flight_server.py -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
