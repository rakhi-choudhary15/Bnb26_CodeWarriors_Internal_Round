# Debugging Report

## Total Bugs Found
**7 bugs identified** during complete forensic audit.

## P0 Bugs
- **BUG-001**: `POST /api/assets/upload-url` 503 DATABASE_ERROR when `project_id` is supplied in request body (`StatementError: 'str' object has no attribute 'hex'`). **[FIXED & VERIFIED]**

## P1 Bugs
- **BUG-002**: `backend/tests/test_e2e_critical_flow.py` fails with missing `client` fixture. **[FIXED & VERIFIED]**
- **BUG-003**: `request_upload` does not verify project ownership (IDOR vulnerability permitting cross-user asset attachment). **[FIXED & VERIFIED]**

## P2 Bugs
- **BUG-004**: Backend Ruff static analysis failures (17 lint violations across routes and tests). **[FIXED & VERIFIED]**
- **BUG-005**: Playwright driver binary 404 download failure on Windows x64 in browser test subagent environment. **[BLOCKED - EXTERNAL CDN]**
- **BUG-006**: Frontend `App.tsx` hardcoded backend host URLs and demo dev token. **[FIXED & VERIFIED]**

## P3 Bugs
- **BUG-007**: Route collision between `@app.get("/demo")` and `app.mount("/demo")` in `main.py`. **[FIXED & VERIFIED]**

## Bugs Fixed
- **BUG-001** (P0)
- **BUG-002** (P1)
- **BUG-003** (P1)
- **BUG-004** (P2)
- **BUG-006** (P2)
- **BUG-007** (P3)

## Bugs Blocked
- **BUG-005** (P2): Upstream Microsoft Playwright Azure edge CDN returned 404 for driver binary version 1.57.0 on Windows x64. Direct runtime testing was performed via HTTP and browser inspection on ports 8000 and 3000.

## Root Causes
1. **BUG-001**: In `create_upload_url`, `body.project_id` was passed as a raw string into `Asset(project_id=project_id)`. SQLAlchemy's UUID type expects a `uuid.UUID` and calls `.hex` on the parameter, throwing `AttributeError: 'str' object has no attribute 'hex'`.
2. **BUG-002**: The `client` TestClient fixture was defined locally in `tests/test_api.py` rather than globally in `tests/conftest.py`, blocking other test files from running.
3. **BUG-003**: `request_upload` accepted `project_id` without verifying that the project exists and belongs to the requesting `owner_id`.
4. **BUG-004**: Leftover unused imports, missing exception chaining (`raise ... from exc`), and unneeded f-string prefixes in genome, intelligence, platforms, and references routes.
5. **BUG-006**: Frontend prototype had hardcoded strings for `http://127.0.0.1:8000/` and lacked Vite client types (`vite-env.d.ts`).
6. **BUG-007**: Both an explicit `@app.get("/demo")` handler and a `StaticFiles` mount on `/demo` were registered on the same router path.

## Files Changed
- `backend/app/modules/assets/service.py`: Coerced `project_id` to UUID and enforced project ownership check.
- `backend/tests/conftest.py`: Added global `client` fixture, `_stamp_head`, `_drain_jobs`, and session overrides.
- `backend/tests/test_api.py`: Removed duplicate `client` fixture and added regression tests for project-associated asset uploads.
- `backend/tests/test_e2e_critical_flow.py`: Fixed imports and enabled end-to-end critical flow regression testing.
- `backend/app/api/routes/genome.py`: Cleaned imports, fixed B904 exception chaining and f-string prefix.
- `backend/app/api/routes/intelligence.py`: Fixed unused variable and exception chaining.
- `backend/app/api/routes/platforms.py`: Removed unused import and fixed exception chaining.
- `backend/app/api/routes/references.py`: Fixed exception chaining in reference routes.
- `backend/app/main.py`: Resolved route collision on `/demo`.
- `apps/web/src/App.tsx`: Added dynamic `API_BASE` and `MASTER_SUITE_URL`.
- `apps/web/src/vite-env.d.ts`: Added Vite client type declarations.
- `docs/BUG-LEDGER.md`: Documented all discovered issues, fixes, and verification statuses.

## Tests Added
- `tests/test_api.py::test_upload_ticket_with_project_id_succeeds`
- `tests/test_api.py::test_upload_ticket_for_unowned_project_rejected`
- `tests/test_api.py::test_upload_ticket_with_invalid_project_id_rejected`
- `tests/test_e2e_critical_flow.py::test_full_critical_demo_user_flow` (unblocked and verified)

## Tests Passed
- **118 out of 118 unit & integration tests passed** via `pytest` (100% pass rate).
- **Ruff static analysis checks**: 0 errors ("All checks passed!").
- **Vite frontend build**: `tsc && vite build` completed with 0 errors.

## Tests Remaining
- **0 remaining failing tests**.

## Runtime Verification
- **Port 8000 (FastAPI Backend)**: Active and verified at `http://127.0.0.1:8000/`.
  - `GET /` -> 200 (72,782 bytes)
  - `GET /demo` -> 200 (72,782 bytes)
  - `GET /api/health` -> 200 (463 bytes)
  - `GET /api/docs` -> 200 (1,019 bytes)
  - `GET /api/openapi.json` -> 200 (39,102 bytes)
- **Port 3000 (Vite Web App)**: Active and verified at `http://localhost:3000/`.
  - Responsive with status 200 and Vite HMR active.

## Critical Demo Flow
Verified end-to-end with the demo brief:
`"I want to create a 30-second energetic dance Reel for Instagram."`

1. **Intent Creation & Analysis**: `POST /api/creation/intents` -> 201 Created
2. **Blueprint Generation**: `POST /api/creation/blueprints` -> 201 Created (9 stages)
3. **Workflow Instantiation**: `POST /api/projects/:id/workflows` -> 201 Created (9 steps)
4. **Step Execution**: `POST /api/workflows/:id/steps/:id/run` -> 200 OK (inline concept generation)
5. **Step Review & Advancement**: `PATCH /api/workflows/:id/steps/:id` -> 200 OK (unlocks step 1)
6. **Reference DNA Analysis**: `POST /api/references` -> 201, `POST /api/references/analyze` -> 200 OK
7. **Asset Ingest Reservation**: `POST /api/assets/upload-url` with `project_id` -> 201 Created (formerly P0 bug, now fully working)
8. **Content Genome Retrieval**: `GET /api/content-genome/:project_id` -> 200 OK (7 graph nodes)
9. **Impact Propagation**: `POST /api/content-genome/propagate` -> 200 OK (impact event created)
10. **Impact Resolution**: `POST /api/content-genome/impacts/:id/resolve` -> 200 OK
11. **Platform Adaptation**: `POST /api/platform/adapt` -> 200 OK (4 variants generated)
12. **Publishing Package**: `POST /api/publishing/jobs` -> 201 Created
13. **Creator Intelligence**: `GET /api/creator-intelligence` -> 200 OK
14. **Content Archaeology**: `GET /api/content-opportunities` -> 200 OK

## Known Limitations
- Media rendering requires FFmpeg installed on the host system; when absent, the system degrades honestly reporting `media.ok: false` while continuing full intent, concept, script, genome, adaptation, and intelligence flows.
- Automated browser subagent driver download was blocked by Microsoft Azure Playwright CDN 404 for Windows x64 driver 1.57.0.
