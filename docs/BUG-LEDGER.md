# CreatorAI Bug Ledger

Master audit log of all discovered issues, root causes, severity ratings, reproduction steps, fixes, and regression verifications.

---

## Severity Definitions
- **P0** — Application / demo blocker; critical crash; fundamental workflow failure.
- **P1** — Major functionality broken; security vulnerability; data integrity issue; core skill failure.
- **P2** — Moderate bug; non-fatal API inconsistency; edge-case failure; UI state anomaly.
- **P3** — Minor polish; documentation drift; cosmetic warning.

## Status Definitions
`DISCOVERED` | `REPRODUCING` | `ROOT_CAUSE_FOUND` | `FIX_IN_PROGRESS` | `FIXED` | `VERIFIED` | `REGRESSION_VERIFIED` | `BLOCKED` | `WONT_FIX`

---

## Active & Discovered Issues Summary

| Bug ID | Title | Severity | Category | Status |
|---|---|---|---|---|
| **BUG-001** | `POST /api/assets/upload-url` 503 DATABASE_ERROR when `project_id` provided | P0 | API / DATABASE | REGRESSION_VERIFIED |
| **BUG-002** | `test_e2e_critical_flow.py` fails with missing `client` fixture | P1 | TEST | REGRESSION_VERIFIED |
| **BUG-003** | `request_upload` does not verify project ownership (IDOR vulnerability) | P1 | SECURITY / AUTH | REGRESSION_VERIFIED |
| **BUG-004** | Backend Ruff static analysis failures (17 lint violations) | P2 | BUILD / CODE QUALITY | REGRESSION_VERIFIED |
| **BUG-005** | Playwright driver 404 on Windows x64 in browser test subagent | P2 | TEST / CONFIGURATION | BLOCKED |
| **BUG-006** | Frontend `App.tsx` hardcoded backend host URLs and demo dev token | P2 | FRONTEND | REGRESSION_VERIFIED |
| **BUG-007** | Route collision between `@app.get("/demo")` and `app.mount("/demo")` in `main.py` | P3 | API / BACKEND | REGRESSION_VERIFIED |

---

## Detailed Bug Records

## BUG-001

Title: `POST /api/assets/upload-url` crashes with 503 DATABASE_ERROR (`StatementError: 'str' object has no attribute 'hex'`) when `project_id` is supplied
Severity: P0
Category: API / DATABASE
Status: REGRESSION_VERIFIED
Detected By: Forensic API probe & TestClient inspection
Affected Area: Asset Upload / Ingestion pipeline
File(s):
- `backend/app/modules/assets/schemas.py`
- `backend/app/api/routes/assets.py`
- `backend/app/modules/assets/service.py`
Endpoint/Route: `POST /api/assets/upload-url`
Reproduction:
```python
client.post(
    "/api/assets/upload-url",
    json={
        "filename": "take1.mp4",
        "mime": "video/mp4",
        "size_bytes": 1048576,
        "kind": "video",
        "project_id": "9bbf034f-686f-4bd2-9f4f-8fd991d875e5",
    },
    headers={"Authorization": "Bearer dev:00000000-0000-0000-0000-000000000001"},
)
```
Expected Behavior: Returns 201 Created with upload ticket `{asset_id, upload_url, expires_in, method: "PUT", ...}`.
Actual Behavior: Returns 503 Service Unavailable with `{"error": {"code": "DATABASE_ERROR", "message": "The database could not complete this request."}}`.
Root Cause: `RequestUploadRequest.project_id` is defined as `str | None`. In `create_upload_url`, `body.project_id` was passed as a raw string into `asset_service.request_upload` and assigned to `Asset(project_id=project_id)`. SQLAlchemy's UUID column type calls `.hex` on the parameter. When a `str` is passed instead of `uuid.UUID`, Python raises `AttributeError: 'str' object has no attribute 'hex'`, causing a `StatementError` which triggers `DATABASE_ERROR`.
Fix:
In `backend/app/modules/assets/service.py`:
1. Coerced and validated `project_id` to `uuid.UUID` if provided.
2. Verified project ownership against `owner_id`.
3. Assigned validated `proj_uuid` to `Asset.project_id`.
Verification: Verified with unit tests and live HTTP probe against `http://127.0.0.1:8000/api/assets/upload-url` returning 201 Created.
Regression Test: `tests/test_api.py::test_upload_ticket_with_project_id_succeeds`
Notes:

---

## BUG-002

Title: `backend/tests/test_e2e_critical_flow.py` fails with `fixture 'client' not found`
Severity: P1
Category: TEST
Status: REGRESSION_VERIFIED
Detected By: Initial `pytest` run
Affected Area: End-to-end regression testing
File(s):
- `backend/tests/conftest.py`
- `backend/tests/test_api.py`
- `backend/tests/test_e2e_critical_flow.py`
Endpoint/Route: N/A
Reproduction:
```bash
pytest tests/test_e2e_critical_flow.py
```
Expected Behavior: Test suite runs the end-to-end critical flow and passes.
Actual Behavior: Pytest aborts with `ERROR at setup of test_full_critical_demo_user_flow: fixture 'client' not found`.
Root Cause: `client` fixture (and associated helpers `_stamp_head`, `_override_session`, `_drain_jobs`) was implemented inside `tests/test_api.py` rather than `tests/conftest.py`, making it inaccessible to other test files.
Fix: Moved `client` fixture and helper functions to `backend/tests/conftest.py` so all tests have access to `client: TestClient`.
Verification: `pytest tests/test_e2e_critical_flow.py` passes 100%.
Regression Test: `pytest tests/test_e2e_critical_flow.py::test_full_critical_demo_user_flow`
Notes:

---

## BUG-003

Title: `request_upload` does not verify project ownership before attaching asset
Severity: P1
Category: SECURITY / AUTH
Status: REGRESSION_VERIFIED
Detected By: Security / Auth Code Review
Affected Area: Asset Ingestion & Project Data Isolation
File(s):
- `backend/app/modules/assets/service.py`
Endpoint/Route: `POST /api/assets/upload-url`
Reproduction:
User A requests upload URL specifying `project_id` belonging to User B.
Expected Behavior: Returns 404 Not Found per AGENTS.md §9 ("ownership -> 404").
Actual Behavior: Asset was created with `project_id` of User B, allowing User A to attach assets to User B's project without authorization.
Root Cause: `request_upload` never queried the `projects` table to check that `project_id` exists and is owned by `owner_id`.
Fix: Query `Project` with `id=proj_uuid, owner_id=owner_id`. If not found, raise `NotFoundError("Project not found.")`.
Verification: Verified with unit test asserting 404 on unowned project attachment.
Regression Test: `tests/test_api.py::test_upload_ticket_for_unowned_project_rejected`
Notes: Critical security issue according to SECURITY.md §1 & AGENTS.md §9.

---

## BUG-004

Title: Backend Ruff static analysis failures (17 lint violations)
Severity: P2
Category: BUILD / CODE QUALITY
Status: REGRESSION_VERIFIED
Detected By: `python -m ruff check .`
Affected Area: Backend routes & test code
File(s):
- `backend/app/api/routes/genome.py`
- `backend/app/api/routes/intelligence.py`
- `backend/app/api/routes/platforms.py`
- `backend/app/api/routes/references.py`
- `backend/tests/test_e2e_critical_flow.py`
Endpoint/Route: N/A
Reproduction:
```bash
ruff check .
```
Expected Behavior: Clean lint pass with 0 errors.
Actual Behavior: 17 violations found (F401 unused imports, F541 redundant f-string, B007 unused loop var, B904 bare exception raises, I001 unsorted imports).
Root Cause: Incomplete cleanup during rapid development of genome, platforms, references, and test files.
Fix: Cleaned up unused imports, fixed exception chaining (`from None` / `from exc`), removed empty f-string prefix, formatted imports.
Verification: `python -m ruff check .` outputs "All checks passed!".
Regression Test: `python -m ruff check .`
Notes:

---

## BUG-005

Title: Playwright driver download failure (404) in browser subagent environment
Severity: P2
Category: TEST / CONFIGURATION
Status: BLOCKED
Detected By: Browser subagent invocation
Affected Area: Automated browser testing
File(s): N/A (Subagent Playwright driver)
Endpoint/Route: N/A
Reproduction:
Browser subagent attempted `open_browser_url`.
Expected Behavior: Playwright driver initializes and launches Chromium.
Actual Behavior: Driver download returned HTTP 404 from `https://playwright.azureedge.net/builds/driver/playwright-1.57.0-win32_x64.zip`.
Root Cause: Upstream Microsoft Playwright Azure edge CDN returned 404 for driver binary version 1.57.0 on Windows x64.
Fix: External driver binary issue on Microsoft CDN. Browser functionality is directly validated through the running Vite frontend on port 3000 and the FastAPI master suite on port 8000.
Verification: Direct HTTP and SPA validation.
Regression Test: N/A
Notes: Documented as BLOCKED per user instructions §25.

---

## BUG-006

Title: Frontend `App.tsx` hardcoded backend host URLs and demo dev token
Severity: P2
Category: FRONTEND
Status: REGRESSION_VERIFIED
Detected By: Frontend code review
Affected Area: Web App navigation & API client
File(s): `apps/web/src/App.tsx`, `apps/web/src/vite-env.d.ts`
Endpoint/Route: `/`
Reproduction: Inspect `App.tsx` lines 53, 115.
Expected Behavior: Uses dynamic base URL or relative paths (`/` or `import.meta.env.VITE_API_URL`).
Actual Behavior: Hardcoded `http://127.0.0.1:8000/`.
Root Cause: Quick hackathon demo wiring in web prototype.
Fix:
1. Replaced hardcoded URLs with dynamic constants (`API_BASE` and `MASTER_SUITE_URL`).
2. Added `vite-env.d.ts` to provide TypeScript types for `import.meta.env`.
Verification: `npm run build` in `apps/web` succeeds without errors.
Regression Test: `npm run build`
Notes:

---

## BUG-007

Title: Route collision between `@app.get("/demo")` and `app.mount("/demo")` in `main.py`
Severity: P3
Category: API / BACKEND
Status: REGRESSION_VERIFIED
Detected By: Code inspection of `main.py`
Affected Area: Demo static file serving
File(s): `backend/app/main.py`
Endpoint/Route: `/demo`
Reproduction: In `_mount_demo()`, line 122 registers `@app.get("/demo")`, then line 126 called `app.mount("/demo", ...)`.
Expected Behavior: Clean route mounting without collision.
Actual Behavior: Starlette route tree warning/shadowing.
Root Cause: Redundant `@app.get("/demo")` before `StaticFiles(..., html=True)` mount on the same path.
Fix: Mounted static directory on `/static` while retaining `@app.get("/")` and `@app.get("/demo")` to return `demo.html` cleanly.
Verification: Both `GET /` and `GET /demo` return 200 with 72782 bytes.
Regression Test: `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/demo')"`
Notes:
