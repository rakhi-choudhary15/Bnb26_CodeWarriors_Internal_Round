# CreatorAI
> Tell us what you want to create. We'll build the workflow.

## What & Why
CreatorAI is an **intent-driven creator operating system**. Instead of learning dozens of tools, you type what you want to create ("a 30-second energetic dance Reel"). CreatorAI interprets the intent, builds a Creation Blueprint, composes a workflow from reusable AI skills, and guides you from idea → script → shot plan → footage understanding → clips → editing → platform adaptation → publishing → creator intelligence.

Differentiators: Intent→Workflow→Skills, AI Creative Director, Content Genome, Impact Propagation, Content Archaeology, Creator DNA, Reference DNA, editable AI output. See `docs/COMPETITOR-ANALYSIS.md`.

## Core Workflow
USER → Intent Engine → Creation Blueprint → Workflow Engine → Skill Router → Model Gateway → Validation → DB → UI.

## Architecture Overview
Modular monolith: Next.js frontend, FastAPI backend, RQ workers (FFmpeg/OpenCV/STT), Supabase (Postgres+pgvector, Storage, Auth), Redis. Details: `docs/ARCHITECTURE.md`, `docs/AI-ARCHITECTURE.md`.

## Tech Stack
Next.js, React, TypeScript, Tailwind, shadcn/ui, Framer Motion · Python, FastAPI, Pydantic, SQLAlchemy · Supabase · Redis + RQ · FFmpeg, OpenCV · Whisper-compatible STT · multimodal LLM + embeddings behind a gateway. See `docs/TECH-STACK.md`.

## Local Setup (target; scaffolding is created in Phase 0 of `docs/IMPLEMENTATION-PLAN.md`)
```bash
git clone <repo> && cd creatorai
cp .env.example .env            # fill values
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
rq worker --url $REDIS_URL default     # separate terminal (needs ffmpeg installed)
# Frontend
cd ../apps/web && pnpm install && pnpm dev
```
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
