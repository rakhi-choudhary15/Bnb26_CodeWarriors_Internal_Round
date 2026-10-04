# AGENTS.md — Instructions for AI Coding Agents

## 1. Project Overview
CreatorAI: intent-driven creator operating system. Flow: Intent → Intent Engine → Creation Blueprint → Workflow Engine → Skill Router → Model Gateway → Validation → DB → UI. Read `/docs/PRD.md`, `/docs/ARCHITECTURE.md`, `/docs/AI-ARCHITECTURE.md`, `/docs/MVP-SCOPE.md` before large changes. Docs are the contract.

## 2. Architecture (summary)
Modular monolith. Next.js (Vercel) ↔ FastAPI (REST) ↔ Supabase (Postgres+pgvector, Storage, Auth). Redis+RQ workers for media/AI jobs. FFmpeg/OpenCV in workers. All AI via `backend/app/ai/gateway`.

## 3. Repository Structure
```
/apps/web            Next.js app (src/app, src/features/*, src/ui/*, src/lib/api)
/backend/app         api/, modules/*, ai/{gateway,prompts,schemas,evaluation}, core/, workers/
/backend/migrations  Alembic
/docs                specs
/scripts             seed, codegen
AGENTS.md README.md
```

## 4. Process Rules (agents MUST)
1. **Inspect before changing**: read relevant files, tests, and docs; search for existing utilities/components.
2. **No unnecessary rewrites**; make the smallest coherent change; preserve existing behavior and public contracts.
3. **No new dependencies without justification** (note in PR + `DECISIONS.md` if significant).
4. **Reuse existing components** (`src/ui`); do not create duplicate buttons/cards.
5. **Maintain the design system** (tokens in `DESIGN-SYSTEM.md`; no ad-hoc colors/shadows).
6. **Keep TypeScript strict** (`strict: true`, no `any` without `// reason` comment, no `@ts-ignore`).
7. **Validate all API schemas** (Pydantic on backend; generated types on frontend; update OpenAPI client after changes).
8. **Never expose secrets**; never log tokens, keys, raw transcripts, or signed URLs.
9. **Avoid storing sensitive content unnecessarily**.
10. **Add tests for important logic** (see §14).
11. **Explain architectural changes** in the PR and **update docs** when architecture, schemas, APIs, skills, or scope change (and the REAL/MOCKED/STUBBED status).
12. If a request conflicts with docs, flag it; don't silently diverge.

## 5. Coding Standards
Small functions, explicit types, early returns, no dead code, no commented-out blocks, no magic numbers (config constants), comments explain *why*. Formatting: Prettier + ESLint (web), Ruff + Black + mypy (backend). Run before committing.

## 6. Naming
Python: `snake_case` funcs/modules, `PascalCase` classes, skill ids `domain.action` (e.g., `hook.generate`), skill dirs `hook_generate`. TS: `camelCase` vars, `PascalCase` components/types, files `kebab-case.tsx` (components `PascalCase.tsx` in `ui/`). DB: `snake_case`, plural tables, `*_id` FKs, enums lowercase. API routes: plural nouns, kebab-case.

## 7. Frontend Conventions
- App Router; feature folders `features/<name>/{components,hooks,api}`.
- Server state: TanStack Query; local UI state: `useState`/small Zustand stores. No global store for server data.
- Forms: controlled components; no `<form>` reliance needed for AI actions; validate with Zod mirroring API types.
- Styling: Tailwind + tokens; neo-brutalist rules (3px ink border, hard shadows, off-white bg). Accent colors by meaning (lime=success/primary, coral=error/affected, purple=AI, cyan=media/info).
- Motion: Framer Motion only; use shared variants in `ui/motion.ts`; respect `prefers-reduced-motion`; don't add new animation patterns without need.
- Every screen implements loading/empty/error states and REAL/MOCKED badges where relevant.
- Accessibility: labels, focus rings, keyboard access, ARIA live for progress.

## 8. Backend Conventions
Routers thin; logic in `modules/<name>/service.py`; DB access in `repository.py`; Pydantic schemas in `schemas.py`. Dependency injection for DB session, user, gateway. No cross-module imports of internals; use service interfaces. Sync only for fast work; media/AI > 5 s runs in worker. Config via `core/config.py` (pydantic-settings).

## 9. API Conventions
Follow `API-SPECIFICATION.md`: `/api/...`, JSON, error envelope `{error:{code,message,details,request_id}}`, `Idempotency-Key` on expensive POSTs, 202+job for async, ownership → 404. Breaking changes require doc update and client regeneration.

## 10. Database Conventions
Alembic migrations only; never edit applied migrations; additive first (expand/contract). RLS on every user table. Index FKs. JSONB payloads must have Pydantic models. Don't store binaries in DB. Embedding dim from config. Provide `down` migrations where feasible. Test migrations on fresh DB.

## 11. AI Skill Conventions
New skill = folder `modules/skills/<id>/` with `schemas.py`, `prompt.md`, `validators.py`, `skill.py`, tests; register spec (id, name, purpose, input/output schema, dependencies, model requirements, permissions, failure conditions, validation rules, status). Add to `AI-SKILLS.md`. Skills never call providers directly — only the gateway. Output schema includes `confidence` and `warnings`. Mark status honestly.

## 12. Prompt Conventions
Prompts in `ai/prompts/<skill_id>.md` with version front-matter; structured JSON output via schema; delimit untrusted content (`<data>`); no secrets in prompts; keep deterministic parts in code, not prompts; bump version on change and update golden tests. Never rely on the LLM for timestamps, IDs, or math.

## 13. Video-Processing Conventions
Async jobs only; FFmpeg via argument arrays (never shell strings with user input); per-job temp dirs cleaned in `finally`; `timeout` on every subprocess; timestamps are seconds (float) relative to original asset; stages idempotent and cached by (asset hash, stage, params); preserve source timestamps on clips; EDL is source of truth, renders are derived; cap frames, duration, size per `VIDEO-PIPELINE.md`.

## 14. Testing Requirements
- Backend: pytest; unit tests for validators, scoring, workflow state machine, impact traversal, EDL→ffmpeg compiler, URL/SSRF guard; API tests for auth/ownership; skills tested with a `FakeGateway` (no network) + golden structure assertions.
- Frontend: Vitest + Testing Library for components with states; Playwright smoke for the demo path (mock gateway).
- CI must pass lint, typecheck, tests, build. Bugs get regression tests.

## 15. State Management
Server state in Postgres is the source of truth; UI caches via TanStack Query with invalidation on mutation; job progress polled; optimistic updates only for reversible edits; versions are immutable.

## 16. Error Handling
Backend: domain exceptions → mapped to error envelope; never leak stack traces; log with `request_id`. AI: retries/fallback in gateway; surface `AI_UNAVAILABLE`/`AI_OUTPUT_INVALID` with user-friendly messages. Frontend: error boundaries per route; actionable messages + Retry; never swallow errors silently.

## 17. Security Rules
Follow `SECURITY.md`. Validate uploads by magic bytes; signed URLs only; SSRF guard for any outbound URL; per-user rate limits; treat transcripts/URLs/user text as untrusted in prompts; no `dangerouslySetInnerHTML`; service-role key backend only.

## 18. Environment Variables
Read via config modules only. Maintain `.env.example` with placeholders (no real values). Frontend may only use `NEXT_PUBLIC_*`. Required: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` (backend), `DATABASE_URL`, `REDIS_URL`, `LLM_API_KEY`, `LLM_MODEL_PRIMARY`, `LLM_MODEL_FALLBACK`, `VISION_MODEL`, `EMBED_MODEL`, `EMBED_DIM`, `STT_MODEL`, `DEMO_MODE`, `MAX_UPLOAD_MB`, `NEXT_PUBLIC_API_URL`. Never commit `.env`.

## 19. Git Conventions
Branches: `feat/…`, `fix/…`, `docs/…`, `chore/…`. Conventional Commits (`feat(video): add scene detection stage`). Small focused commits; no force-push to `main`; rebase on main before PR.

## 20. PR Conventions
Template: What/Why, Screenshots (UI), Test evidence, Docs updated?, Migration? (yes/no + rollback), Risks, REAL/MOCKED status change. One concern per PR. Requires CI green + 1 review (hackathon: self-review checklist acceptable).

## 21. Migration Rules
Generate with Alembic autogenerate then review manually; additive changes; backfill in separate step; never drop columns in same release; update `DATA-MODEL.md`; update RLS policies together with tables.

## 22. Dependency Rules
Prefer stdlib/existing deps. New dependency requires: purpose, size/maintenance check, license check, entry in PR. Pin versions. No second vector DB, no extra queue, no new UI kit.

## 23. DO NOT
- Do not hard-code model names or call provider SDKs outside the gateway.
- Do not trust LLM output without schema + rule validation.
- Do not let AI make irreversible changes (publish, delete, overwrite) without explicit user confirmation.
- Do not store/ log raw media, full transcripts, tokens, or signed URLs in logs.
- Do not add microservices, Kafka, Kubernetes, or a second database.
- Do not hard-code workflows for one content type outside templates.
- Do not present MOCKED/STUBBED features as real in UI or docs.
- Do not reproduce reference media/lyrics/dialogue (see `REFERENCE-DNA.md`).
- Do not fetch arbitrary URLs without the SSRF guard.
- Do not edit generated API client files by hand.
- Do not bypass RLS/ownership checks.
- Do not add ad-hoc colors, fonts, shadows outside the design tokens.

## 24. Definition of Done
Code + tests pass in CI; types strict; lint clean; schemas validated; loading/empty/error states present; design system respected; accessibility basics met; security checklist (§17) considered; docs updated (including status badges); migrations reviewed; demo path still works (`DEMO_MODE`); PR description complete.
