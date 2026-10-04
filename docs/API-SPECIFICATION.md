# API Specification (REST, JSON)

Base: `/api`. Auth: `Authorization: Bearer <Supabase JWT>` on all routes except `/api/health`. Authorization: resource must belong to `owner_id = jwt.sub` else `404` (not 403, to avoid leakage). OpenAPI at `/api/openapi.json`; TS client generated from it.

**Conventions**
- Request/response validated with Pydantic; unknown fields rejected (`extra=forbid`).
- IDs are UUIDs. Times in seconds (float). Dates ISO-8601 UTC.
- Pagination: `?limit=20&cursor=`. 
- Async operations return `202 {job_id}`; poll `GET /api/jobs/:id`.
- **Idempotency:** `Idempotency-Key` header on POSTs that create/start expensive work (`/video/analyze`, `/clips/generate`, `/edits/:id/render`, `/content-genome/propagate`, `/archaeology/scan`). Same key+body within 24 h returns the original response.
- **Error shape:** `{"error":{"code":"VALIDATION_ERROR","message":"…","details":{…},"request_id":"…"}}`
- Error codes: `VALIDATION_ERROR 422`, `UNAUTHENTICATED 401`, `NOT_FOUND 404`, `CONFLICT 409`, `UNSUPPORTED_MEDIA 415`, `FILE_TOO_LARGE 413`, `RATE_LIMITED 429`, `AI_UNAVAILABLE 503`, `AI_OUTPUT_INVALID 502`, `JOB_FAILED 500`.
- Rate limits (per user): 60 req/min general; AI endpoints 10/min; uploads 20/hour.

## Creation
**POST /api/creation/intents** → 201
Req: `{primary_text: str(5..500), details_text?: str(≤1000)}` → creates project + intent, runs `intent.analyze`.
Res: `{project_id, intent: {id, parsed: {content_type, format, platform, duration_s, tone[], style[], audience, required_assets[], required_skills[], stages[], expected_output}, confidence:{…}, assumptions[]}}`
Errors: 422, 429, 503 (falls back to generic low-confidence intent with `fallback:true`).

**GET /api/creation/intents/:id** — returns intent + parse status.

**PATCH /api/creation/intents/:id** — Req: partial `parsed` fields. Res: updated intent.

**POST /api/creation/blueprints** — Req: `{intent_id}`. Res 201: `{blueprint: {id, template_key, stages:[{key,title,skill_ids[],goal,optional,impl_status}], expected_output}}`.

**GET /api/blueprints/:id**, **PATCH /api/blueprints/:id** (reorder/add/remove stages; skills must exist; else 422).

## Projects / Workflows
**GET /api/projects** list. **GET /api/projects/:id** → project with intent, blueprint, workflow summary.
**POST /api/projects/:id/workflows** — Req `{blueprint_id}`. Res 201 workflow with `workflow_steps`.
**GET /api/projects/:id/workflows**. **POST /api/workflows/:id/steps/:stepId/run** → 200 result or 202 job. **PATCH /api/workflows/:id/steps/:stepId** `{status: "done"|"skipped"}` (accept/skip).

## Assets
**POST /api/assets/upload-url** — Req `{filename, mime, size_bytes, kind, project_id?}`; validates allowlist (video/mp4, video/quicktime, audio/mpeg, audio/wav, audio/mp4, image/jpeg, image/png, text/plain, application/pdf) and size (video ≤ 200 MB MVP). Res `{asset_id, upload_url, expires_in}`.
**POST /api/assets/complete** — `{asset_id}` → 202 `{job_id}` (sniffing + probe).
**GET /api/assets?kind=&project_id=** ; **GET /api/assets/:id** (includes short-lived `signed_url`); **PATCH /api/assets/:id** (tags, kind); **DELETE /api/assets/:id**.

## Scripts & Hooks
**POST /api/hooks/generate** — `{project_id, count?: 3..8, style_hints?}` → `{hooks:[{id,text,style,score,reason}]}`.
**POST /api/scripts/generate** — `{project_id, hook_id?, instructions?}` → script v1 `{script_id, version, lines:[{id,beat,text,kind}], cta, caption, title, description, hashtags[]}`.
**PATCH /api/scripts/:id** — `{base_version, lines}` → new version; `409` if base_version stale. Response includes `impact: {event_id, count}` if dependents exist (see propagate).
**GET /api/scripts/:id/versions**.

## References & Shots
**POST /api/references** — `{project_id, asset_id? | url?, attribution?}`; URL fetch is SSRF-guarded (see SECURITY); 422 for non-allowlisted scheme/host.
**POST /api/references/analyze** — `{reference_id}` → 202 job → `reference_dna`.
**GET /api/references/:id/dna**.
**POST /api/shots/plan** — `{project_id, reference_id?}` → `{shot_plan:{id, total_duration_s, shots:[{n,start_s,end_s,framing,distance_m,camera_height,action,lighting,background,notes}]}}`.
**PATCH /api/shots/:id**.

## Video / Clips / Edits
**POST /api/video/analyze** — `{asset_id, script_id?}` → 202 `{job_id}`. Stages: probe, audio, transcript, scenes, captions, embeddings, match.
**GET /api/video/:assetId/analysis** → `{status, stages, transcript:[{start_s,end_s,text}], scenes:[{start_s,end_s,caption,keyframe_url}], matches:[{line_id,start_s,end_s,score,method}]}`.
**POST /api/clips/generate** — `{asset_id, platform, target_duration_s?, count?: 1..10, script_id?}` → 202 → `clips:[{id,start_s,end_s,reason,confidence,target_platform,score_breakdown}]`.
**PATCH /api/clips/:id** — `{start_s?, end_s?, status?}`; validated 0 ≤ start < end ≤ duration.
**POST /api/edits/suggest** — `{clip_id}` → `{edit:{id,version,edl:{tracks…},suggestions:[{id,type,start_s,end_s,detail,confidence,applied}]}}`; types: `trim, caption, reframe, transition, broll, music`.
**PATCH /api/edits/:id** — apply/dismiss suggestions or edit EDL; creates new version.
**POST /api/edits/:id/render** — `{aspect:"9:16", burn_captions:bool}` → 202 `{job_id}`; result `{render_asset_id, signed_url}`.

## Platform & Publishing
**POST /api/platform/adapt** — `{project_id, source_node_id, platforms:[…]}` → `{variants:[{id,platform,aspect,caption,title,description,hashtags,adaptation_notes,impl_status}]}`.
**PATCH /api/variants/:id**.
**POST /api/publishing/jobs** (STUBBED) — returns export package, `impl_status:"stubbed"`.
**GET /api/analytics?project_id=** (MOCKED source flagged `source:"mock"`).

## Content Genome
**GET /api/content-genome/:projectId** → `{nodes:[{id,type,label,state,version}], edges:[{from,to,relation,strength}]}`.
**POST /api/content-genome/propagate** — `{trigger_node_id, before, after}` (Idempotency-Key) → `{impact_event_id, counts:{affected,text_affected,possibly_affected,total}, items:[{node_id,level,reason,suggested_change}]}`.
**POST /api/content-genome/impacts/:eventId/resolve** — `{action:"update_all"|"ignore"|"review", item_ids?, overrides?}` → updated items (updates create new versions, never overwrite).

## Intelligence
**GET /api/creator-dna**; **POST /api/creator-dna/learn** `{asset_ids|script_ids}` → 202.
**GET /api/creator-intelligence** → `{performance, patterns:{repeated_hooks[],durations[]}, gaps[], unused_assets:{minutes,count}, next_ideas[]}`.
**POST /api/archaeology/scan** → 202. **GET /api/content-opportunities?status=&kind=**; **PATCH /api/content-opportunities/:id** (`accepted|dismissed`).
**GET /api/jobs/:id** → `{status,stage,progress,error?,result?}`.
**GET /api/health**.

## DB Mapping
intents→`creation_intents`; blueprints→`creation_blueprints`; workflows→`workflows`,`workflow_steps`; assets→`assets`; hooks→`hooks`; scripts→`scripts`,`script_versions`; references→`references`,`reference_dna`; shots→`shot_plans`; video→`video_analyses`,`transcript_segments`,`scenes`,`script_footage_matches`; clips→`clips`; edits→`edits`; variants→`platform_variants`; genome→`content_nodes`,`content_edges`,`impact_*`; opportunities→`content_opportunities`; jobs→`jobs`.
