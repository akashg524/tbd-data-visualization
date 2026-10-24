# Plan 03-03 Summary: Apache Arrow Flight Server & Columnar Batch Ingestion

## Completed Tasks
1. **Apache Arrow Flight Server (`FederatedFlightServer`)**:
   - Implemented `backend/app/serving/flight.py` subclassing `pyarrow.flight.FlightServerBase`:
     - `do_get`: Extracts SQL from tickets, executes queries via `FederatedExecutor`, and streams Arrow `RecordBatch` streams over gRPC with zero-copy transfers.
     - `list_flights`: Inspects `UnifiedCatalogRegistry` and returns `FlightInfo` descriptors for all virtual schemas and tables.
     - `get_flight_info`: Resolves individual flight descriptor paths and schemas.
     - `start_background` and `stop`: Manages gRPC server lifecycle cleanly on daemon threads.
   - Verified via `tests/test_flight_server.py` (4 passed).

2. **Chunked REST Streaming Export API**:
   - Implemented `backend/app/serving/export.py`:
     - `GET /api/v1/export/query` and `POST /api/v1/export/query` supporting `csv`, `parquet`, and `ndjson` formats.
     - Streams responses using FastAPI `Response` and `StreamingResponse` with appropriate MIME types (`text/csv`, `application/vnd.apache.parquet`, `application/x-ndjson`) and download filenames.
   - Registered `/export` router in `backend/app/api/__init__.py`.
   - Verified via `tests/test_export_api.py` (5 passed).

3. **Application Lifespan & Gateway Server Management**:
   - Updated `backend/app/config.py` with gateway configuration toggles (`enable_pgwire`, `pgwire_host`, `pgwire_port`, `enable_flight`, `flight_host`, `flight_port`).
   - Updated `backend/app/main.py` lifespan context manager to start and stop `PostgresWireServer` and `FederatedFlightServer` cleanly with port collision protections.

## Verification
- `pytest tests/test_flight_server.py tests/test_export_api.py -v`: 9 passed.
- `pytest tests/ -v`: All 85 tests passing green.
- `ruff check backend/ tests/`: Zero lint errors.
