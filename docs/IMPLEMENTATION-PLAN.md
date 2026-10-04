# Implementation Plan

Complexity: S (<2 h), M (2–5 h), L (5–10 h). Team assumption: 3–4 devs (FE, BE, AI/video, design-lite) over ~48 h; phases overlap.

## Phase 0 — Repository setup (S)
Tasks: monorepo (`/apps/web`, `/backend`, `/docs`), env templates, Docker (api, worker, redis), Supabase project + migrations scaffold, CI lint/test, OpenAPI→TS client script, seeded demo data script.
Files: `README.md`, `AGENTS.md`, `backend/pyproject.toml`, `apps/web/package.json`, `.env.example`, `.github/workflows/ci.yml`.
Dependencies: none. Acceptance: `make dev` runs web+api+worker; `/api/health` OK; CI green.

## Phase 1 — Frontend shell + design system (M)
Tasks: Tailwind tokens, Button/Input/Card/Badge/Modal/Stepper, layout shell + rail, page transitions, auth pages.
Files: `apps/web/src/ui/*`, `app/layout.tsx`, `tailwind.config.ts`.
Dep: P0. Acceptance: storybook-like `/ui-kit` page shows all components + states; button motion per spec; reduced-motion honored.

## Phase 2 — Intent engine (M)
Tasks: `ModelGateway` (+ cache, retry, fallback), `intent.analyze`, intent endpoints, Landing + Intent screens.
Files: `backend/app/ai/gateway/*`, `modules/intent/*`, `modules/skills/intent_analyze/*`, `web/features/create/*`.
Dep: P0–1. Acceptance: demo prompt yields valid `CreationIntent` < 10 s; editable chips; fallback works with provider off (cached).

## Phase 3 — Blueprint & workflow (L)
Tasks: skill registry/router, templates (dance, podcast, product_ad, generic), `blueprint.customize`, workflow engine state machine, Blueprint + Project workspace UI.
Files: `modules/skills/registry.py`, `modules/workflow/*`, `modules/blueprint/templates/*.yaml`.
Dep: P2. Acceptance: 3 intents produce 3 different blueprints; startup check validates template skill ids; stage states update.

## Phase 4 — Script + hook (M)
Tasks: `concept/hook/script/caption` skills, script versions, editor UI, Creator DNA stub injection.
Dep: P3. Acceptance: hooks + script with CTA; edit saves new version; est. duration within ±10%.

## Phase 5 — Reference system (M)
Tasks: reference upload, ffmpeg/scene metrics, `reference.analyze`, DNA card, `shot.plan`, `recording.coach`, Shot Planner UI.
Dep: P3–4. Acceptance: Reference DNA metrics sane on 2 sample reels; shot plan ≥ 5 shots, Σ duration ≈ target.

## Phase 6 — Asset upload (M)
Tasks: signed upload, validation worker, asset library UI, RLS + storage policies.
Dep: P0. Acceptance: invalid file rejected; valid file reaches `ready`; signed URL playback works.

## Phase 7 — Video analysis (L)
Tasks: pipeline stages 0–9, jobs table/polling UI, Video Understanding screen, matching view.
Dep: P6, P4. Acceptance: 60 s sample analyzed < 90 s; transcript + scenes + matches visible; stage retry works.

## Phase 8 — Clip generation (M)
Tasks: `clip.generate`, scoring config, review UI.
Dep: P7. Acceptance: ≥ 3 candidates with reason/confidence; timestamps valid; accept/trim persists.

## Phase 9 — Editing (L)
Tasks: `edit.suggest`, EDL model, timeline UI, ASS captions, FFmpeg 9:16 render, platform variant for Reels.
Dep: P8. Acceptance: downloadable 9:16 MP4 with captions; EDL edits create versions.

## Phase 10 — Content Genome (M)
Tasks: nodes/edges creation hooks in skills, graph view, diff + impact traversal, `genome.propagate`, Impact Panel, resolve actions.
Dep: P4, P8. Acceptance: edit a script line → "N content assets affected" with levels; Update all creates new versions; ripple animation.

## Phase 11 — Creator Intelligence (M)
Tasks: Creator DNA card (seed + live update), Archaeology scan on seeded library, opportunities list, Intelligence dashboard (mock analytics badge).
Dep: P6, P10. Acceptance: "You have 47 minutes of unused footage" derived from seeded assets via real query; recommendations labelled MOCKED where applicable.

## Phase 12 — Demo polish (M)
Tasks: demo seed + cached responses, timing rehearsals, error-state sweep, REAL/MOCKED badges, README, record backup video.
Acceptance: DEMO-SCRIPT runs in 3:00 three times in a row on deployed env; fallback project works offline from cache.

## Critical path
P0 → P1/P2 → P3 → P4 → P6 → P7 → P8 → P9 → P10 → P12. P5 and P11 parallelizable.
