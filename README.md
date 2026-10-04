# GenZCreators
> Tell us what you want to create. We'll build the workflow.

## What & Why
**GenZCreators** is an **intent-driven creator operating system**. Instead of learning dozens of tools, you type what you want to create ("a 30-second energetic dance Reel"). GenZCreators interprets the intent, builds a Creation Blueprint, composes a workflow from reusable AI skills, and guides you from idea → script → shot plan → footage understanding → clips → editing → platform adaptation → publishing → creator intelligence.

Differentiators: Intent→Workflow→Skills, AI Creative Director, Content Genome, Impact Propagation, Content Archaeology, Creator DNA, Reference DNA, editable AI output. See `docs/COMPETITOR-ANALYSIS.md`.

## Core Workflow
USER → Intent Engine → Creation Blueprint → Workflow Engine → Skill Router → Model Gateway → Validation → DB → UI.

## Architecture Overview
Modular monolith: React/Vite frontend (`/apps/web`), FastAPI backend (`/backend`), in-process/RQ workers (FFmpeg/OpenCV/STT), SQLite/Supabase, Redis.

## Quick Demo Launch (Round 2 Judges)
1. **Backend & Master Suite (All-in-One):**
   ```bash
   cd backend
   python -m uvicorn app.main:app --port 8000
   ```
   Open **http://127.0.0.1:8000/** to launch the complete 14-stage Neo-Brutalist interactive suite.

2. **Frontend Dev Server (Optional):**
   ```bash
   cd apps/web
   npm run dev
   ```
   Open **http://localhost:3000/** (proxies `/api` to the backend).
Requires: Node 20+, Python 3.11+, FFmpeg, Redis, a Supabase project.

## Environment Variables
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` (backend only), `DATABASE_URL`, `REDIS_URL`, `LLM_API_KEY`, `LLM_MODEL_PRIMARY`, `LLM_MODEL_FALLBACK`, `VISION_MODEL`, `EMBED_MODEL`, `EMBED_DIM`, `STT_MODEL`, `DEMO_MODE`, `MAX_UPLOAD_MB`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`.

## Development Commands
`pnpm dev | build | lint | typecheck | test` · `pytest` · `ruff check . && black --check . && mypy app` · `alembic revision --autogenerate -m "msg"` · `python scripts/seed_demo.py` · `python scripts/gen_api_client.py`.

## MVP
Intent → blueprint → hook/script → reference DNA → shot plan → upload → transcription → script↔footage match → clip generation → edit suggestions → 9:16 export. Genome/Impact/DNA/Archaeology/Intelligence are partial or mocked and labelled. See `docs/MVP-SCOPE.md`.

## Demo Flow
Follow `docs/DEMO-SCRIPT.md` (3 minutes). Use `DEMO_MODE=1` for cached responses.

## Docs
`/docs` contains PRD, tech stack, design system, UX spec, architecture, AI architecture, data model, API, workflow engine, skills, genome, DNA, reference DNA, video pipeline, security, plan, MVP scope, demo script, decisions, competitor analysis. Agents: read `AGENTS.md`.
