# Tech Stack

Principle: **modular monolith, one DB, one queue, provider-agnostic AI.**

## 1. Decisions
| Layer | Choice | Why | Alternatives | Tradeoffs |
|---|---|---|---|---|
| Frontend framework | Next.js (App Router) + React + TypeScript (strict) | Fast routing, Vercel deploy, typed | Vite+React, Remix | SSR unnecessary for most screens, but routing/deploy are free |
| Styling | Tailwind CSS | Utility speed; tokens map to design system | CSS Modules | Needs discipline; solved by DESIGN-SYSTEM tokens |
| Components | shadcn/ui (restyled neo-brutalist) | Owned source, accessible primitives (Radix) | MUI, Chakra | Must override styling heavily |
| Motion | Framer Motion | Spring physics, layout animations, `AnimatePresence` | CSS only, GSAP | Bundle size; use `LazyMotion` |
| Server state | TanStack Query | Polling jobs, cache | SWR | Extra dep, justified by job polling |
| Client state | Zustand (small, local UI only) | Minimal boilerplate | Redux | Keep stores tiny |
| Backend | Python 3.11 + FastAPI + Pydantic v2 | Best AI/video ecosystem; typed schemas; OpenAPI | Node/Nest | Two languages; mitigated by generated TS client |
| ORM | SQLAlchemy 2 + Alembic | Mature migrations | SQLModel, raw SQL | Verbose; use raw SQL for pgvector queries |
| Database | Supabase Postgres + pgvector | Auth+DB+storage+vectors in one | Neon+S3+Pinecone | Vendor coupling; standard Postgres underneath |
| Storage | Supabase Storage (private buckets, signed URLs) | One vendor | S3/R2 | Egress limits; adapter allows swap |
| Auth | Supabase Auth (JWT) | Zero-effort | Clerk, Auth0 | FastAPI verifies JWT |
| Queue | Redis + RQ | Simplest Python queue | Celery, Arq | Fewer features; sufficient |
| Video | FFmpeg (+ PySceneDetect), OpenCV for frame metrics | Industry standard | MoviePy | FFmpeg CLI via subprocess in worker |
| Speech | Whisper-compatible (hosted API or `faster-whisper`) | Word timestamps | Deepgram | Local needs CPU/GPU; hosted default, local fallback |
| LLM | Multimodal LLM behind `ModelGateway` | Swappable | Single SDK calls | Adapter code upfront |
| Embeddings | Embedding model via gateway (dimension configurable, default 1536) | pgvector | — | Re-embed on model change |
| Deploy | Vercel (web), Render/Railway (api + worker + Redis) | Zero-ops | Fly, AWS | Free tiers sleep; keep warm for demo |
| CI | GitHub Actions | Standard | — | — |

## 2. Decision Matrix (1–5, higher better)
| Option | Hackathon speed | AI/video fit | Cost | Team learning | Prod path | Total |
|---|---|---|---|---|---|---|
| Next.js + FastAPI + Supabase (chosen) | 5 | 5 | 4 | 4 | 4 | **22** |
| Next.js full-stack (API routes) + Supabase | 5 | 3 | 4 | 5 | 3 | 20 |
| Django + HTMX | 3 | 5 | 4 | 3 | 4 | 19 |
| Microservices on K8s | 1 | 4 | 1 | 1 | 5 | 12 |

## 3. Cost Considerations
LLM/vision calls dominate. Controls: cache by input hash, sample ≤ 1 frame per 2 s, caption keyframes only, transcribe audio once, cap demo uploads (200 MB / 3 min), log tokens per `skill_runs`.

## 4. Scalability Path
Workers scale horizontally (RQ). Split `video` module into a service only if CPU contention appears. Replace RQ with Celery/Temporal if workflows need durable long-running orchestration. Move storage to S3/R2 via adapter.

## 5. Integration Points
- Frontend ↔ API: REST + OpenAPI-generated TS types; polling for jobs (SSE optional).
- API ↔ Supabase: Postgres via SQLAlchemy; JWT verification; Storage via service key (server only).
- API ↔ Worker: Redis queue; job state in `jobs` table.
- Worker ↔ AI: only through `ModelGateway`.

## 6. Explicitly Excluded
Kubernetes, Kafka, GraphQL, separate vector DB, microservices, Elasticsearch.
