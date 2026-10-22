# TBD Data Visualization Platform

Enterprise-grade, SQL-first financial data visualization platform with federated multi-datasource analytics.

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 20+
- Git

### Backend Setup
```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

# Install dependencies
pip install -e ".[dev]"

# Run the API server
cd backend
uvicorn app.main:app --reload

# Run tests
pytest
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### Docker (Full Stack)
```bash
docker compose up --build
```

## Project Structure
```
tbd-data-visulization/
├── backend/
│   └── app/
│       ├── main.py          # FastAPI application factory
│       ├── config.py         # Pydantic settings
│       ├── engine.py         # DuckDB analytics engine
│       └── api/
│           ├── health.py     # Health & readiness probes
│           ├── datasources.py # Datasource CRUD
│           └── query.py      # SQL execution endpoint
├── frontend/                 # React + TypeScript + Vite
│   └── src/
├── tests/                    # Pytest test suite
├── pyproject.toml            # Python project config (deps, ruff, mypy, pytest)
├── docker-compose.yml        # Full-stack dev orchestration
└── .pre-commit-config.yaml   # Git hooks (lint, format, type-check)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend Framework | FastAPI (Python 3.13) |
| Analytical Engine | DuckDB + PyArrow |
| Frontend | React 19 + TypeScript + Vite |
| Styling | Tailwind CSS v4 |
| Charts | Apache ECharts |
| SQL Editor | Monaco Editor |
| Linting | Ruff |
| Type Checking | Mypy (backend) / TypeScript strict (frontend) |
| Testing | Pytest (backend) / Vitest (frontend) |
