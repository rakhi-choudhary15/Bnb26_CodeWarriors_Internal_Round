# Decision Log

| ID | Decision | Rationale | Alternatives | Consequence |
|---|---|---|---|---|
| D-001 | Treat brief §4 as the problem statement (file not attached) | Only source available | Block and ask | Re-check when statement arrives |
| D-002 | Modular monolith (FastAPI + RQ worker) | Hackathon speed | Microservices | Easy split later |
| D-003 | FastAPI (Python) backend with Next.js frontend | AI/video ecosystem | Node full-stack | Generated TS client bridges languages |
| D-004 | Supabase for DB/Storage/Auth/pgvector | One vendor, fast | Neon+S3+Pinecone | Vendor coupling, standard PG |
| D-005 | RQ over Celery | Simplicity | Celery, Temporal | Revisit for durable workflows |
| D-006 | Skills as registry-based Python modules with Pydantic schemas | Extensible without core changes | Single agent with tools | Startup check validates templates |
| D-007 | Unified `content_nodes`/`content_edges` replaces separate `content_relationships`+`content_dependencies` | One graph, simpler traversal | Two tables | Domain tables link via ref |
| D-008 | Workflow = curated templates + LLM customization (validated) | Reliability + dynamism | Pure LLM planning, pure templates | Unknown intents fall back to generic template |
| D-009 | All timestamps come from STT/scene data, never LLM | Prevent hallucinated cuts | Trust LLM | Validators enforce |
| D-010 | Reference analysis from uploaded files; URLs metadata-only | Copyright/ToS/SSRF | Download via yt-dlp | Less convenient, safer |
| D-011 | EDL JSON is the editing source of truth; renders derived | Editable output | Direct ffmpeg commands | Needs EDL→ffmpeg compiler |
| D-012 | Polling for job progress (SSE later) | Simplicity | WebSockets | 2 s latency acceptable |
| D-013 | Demo cache mode | Reliability on stage | Live-only | Must label cached outputs in dev tools |
| D-014 | No separate `footage` table; `assets(kind=video)` + `video_analyses` | Avoid duplication | footage table | Simpler |
| D-015 | Single-user workspaces; no collaboration | Scope | Teams | Schema keeps `owner_id` for later orgs |
| D-016 | Embedding dim configurable (default 1536) | Model portability | Fixed | Re-embed on change |
| D-017 | Dance footage without speech uses visual+beat matching | Primary demo is dance | Require speech | Confidence capped at 0.7, flagged |
| D-018 | Mark every feature REAL/MOCKED/STUBBED/FUTURE in UI | Honesty | Hide | Slight visual noise |

## OPEN ARCHITECTURAL QUESTIONS
1. **Problem statement missing** — any extra requirements (e.g., mandatory publishing integration) could change scope.
2. **Model provider** — needs one vendor with multimodal + STT + embeddings, or multiple adapters; affects embedding dimension and cost.
3. **Reference URL ingestion** — if judges expect analysis of Instagram/YouTube links, a legal/ToS-compliant ingestion route is needed (D-010 assumes uploads).
4. **Long-running workflows** — if projects span days with background automation, RQ may need replacement by a durable engine.
