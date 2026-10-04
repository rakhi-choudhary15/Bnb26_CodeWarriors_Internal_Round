# Data Model (PostgreSQL / Supabase)

Conventions: `uuid` PKs (`gen_random_uuid()`), `created_at/updated_at timestamptz`, `owner_id uuid` → `auth.users` on all user-owned tables with RLS (`owner_id = auth.uid()`), JSONB for model-shaped payloads validated by Pydantic. Embeddings: `vector(1536)` (dimension set by `EMBED_DIM`; change requires re-embed migration).

## 1. Normalization decisions
- **Unified content graph**: `content_nodes` + `content_edges` represent the Content Genome (ideas, scripts, hooks, footage, clips, variants…). Domain tables (`scripts`, `clips`, `platform_variants`, …) hold type-specific data and have a 1:1 `node_id`. This replaces separate `content_relationships` and `content_dependencies` tables from the brief (see DECISIONS D-007).
- **Versioning**: `script_versions` immutable; `edits` hold EDL JSON with `version`.
- Merged: `footage` = `assets` where `kind='video'` + `video_analyses`; `scenes` and `transcript_segments` separate (high volume, vector search).

## 2. Tables
**profiles** (id=auth uid, display_name, created_at)
**creator_dna** (id, owner_id, version, profile jsonb, sample_count, updated_at) — one current row per owner + history by version.
**projects** (id, owner_id, title, status, intent_id, blueprint_id, workflow_id, cover_asset_id)
**creation_intents** (id, owner_id, project_id, primary_text, details_text, parsed jsonb, confidence jsonb, user_edited bool)
**creation_blueprints** (id, project_id, intent_id, template_key, stages jsonb, expected_output jsonb, version)
**workflows** (id, project_id, blueprint_id, status, current_step_id)
**workflow_steps** (id, workflow_id, position, key, title, skill_ids text[], status enum[locked,ready,running,needs_review,done,failed,skipped], input jsonb, output_ref jsonb, optional bool, impl_status enum[real,mocked,stubbed,future])
**ai_skills** (id text PK, name, purpose, status, spec jsonb, enabled)
**skill_runs** (id, owner_id, project_id, step_id, skill_id, prompt_version, model, input_hash, status, latency_ms, tokens_in, tokens_out, cost_usd, error, output jsonb, created_at)
**assets** (id, owner_id, project_id null, kind enum[video,image,audio,script,reference,creator,brand], filename, storage_path, mime, size_bytes, duration_s, width, height, status enum[pending,processing,ready,rejected,failed], tags text[], meta jsonb, last_used_at)
**asset_embeddings** (id, asset_id, scope enum[asset,frame,segment], ref_start_s, ref_end_s, embedding vector, text) — ivfflat/hnsw index.
**scripts** (id, project_id, node_id, current_version_id, title)
**script_versions** (id, script_id, version, lines jsonb [{id, beat, text, kind}], source enum[ai,user], created_at)
**hooks** (id, project_id, script_id null, text, style, score, selected bool, node_id)
**references** (id, owner_id, project_id, asset_id null, url null, title, creator_attribution, license_note, status)
**reference_dna** (id, reference_id, dna jsonb, confidence, model, created_at)
**video_analyses** (id, asset_id, status, stages jsonb, language, transcript_json jsonb, meta jsonb)
**transcript_segments** (id, asset_id, idx, start_s, end_s, text, speaker, embedding vector)
**scenes** (id, asset_id, idx, start_s, end_s, keyframe_path, caption, tags text[], quality jsonb, embedding vector)
**script_footage_matches** (id, script_version_id, line_id, asset_id, start_s, end_s, score, method enum[semantic,visual,beat,manual], accepted bool)
**shot_plans** (id, project_id, node_id, total_duration_s, shots jsonb [{n,start_s,end_s,framing,distance_m,camera_height,action,lighting,background,notes}], version)
**clips** (id, project_id, node_id, source_asset_id, start_s, end_s, reason, confidence, target_platform, status enum[candidate,accepted,rejected], score_breakdown jsonb)
**edits** (id, project_id, clip_id, version, edl jsonb, suggestions jsonb, render_asset_id null, status)
**platform_variants** (id, project_id, node_id, parent_node_id, platform enum[instagram_reels,youtube_shorts,tiktok,youtube,linkedin,other], aspect, caption, title, description, hashtags text[], render_asset_id null, status, impl_status)
**publishing_jobs** (id, variant_id, status, scheduled_at, external_url, impl_status) — STUBBED
**analytics** (id, variant_id, metric_date, metrics jsonb, source enum[mock,import,api])
**content_nodes** (id, owner_id, project_id, type enum[idea,script,hook,claim,topic,footage,scene,broll,audio,asset,clip,edit,variant,published], ref_table, ref_id, label, content_hash, version, state enum[current,stale,archived], meta jsonb)
**content_edges** (id, owner_id, from_node, to_node, relation enum[derived_from,contains,uses,adapts,quotes,matches], strength real, meta jsonb) — `from_node` = upstream/source; unique (from_node,to_node,relation).
**impact_events** (id, owner_id, project_id, trigger_node_id, change jsonb {before,after,diff_type}, status enum[open,resolved], created_at)
**impact_items** (id, impact_event_id, node_id, level enum[affected,text_affected,possibly_affected], reason, suggested_change jsonb, resolution enum[pending,updated,ignored,reviewed])
**content_opportunities** (id, owner_id, kind enum[short_form,educational_clip,social_post,carousel,new_idea,gap], title, rationale, source_asset_ids uuid[], source_ranges jsonb, effort enum, score, status enum[new,accepted,dismissed], origin enum[archaeology,intelligence])
**jobs** (id, owner_id, type, status, stage, progress, input_hash unique, result jsonb, error, attempts, created_at)

## 3. ER Diagram
```mermaid
erDiagram
  profiles ||--o{ projects : owns
  profiles ||--o| creator_dna : has
  projects ||--|| creation_intents : from
  projects ||--|| creation_blueprints : plans
  projects ||--|| workflows : runs
  workflows ||--o{ workflow_steps : contains
  workflow_steps ||--o{ skill_runs : executes
  ai_skills ||--o{ skill_runs : defines
  projects ||--o{ assets : uses
  assets ||--o{ asset_embeddings : indexed
  assets ||--o| video_analyses : analyzed
  assets ||--o{ transcript_segments : has
  assets ||--o{ scenes : has
  projects ||--o{ scripts : has
  scripts ||--o{ script_versions : versions
  script_versions ||--o{ script_footage_matches : matched
  projects ||--o{ hooks : has
  projects ||--o{ references : has
  references ||--o| reference_dna : analyzed
  projects ||--o| shot_plans : has
  projects ||--o{ clips : has
  clips ||--o{ edits : edited
  projects ||--o{ platform_variants : adapts
  platform_variants ||--o{ publishing_jobs : publishes
  platform_variants ||--o{ analytics : measured
  projects ||--o{ content_nodes : graph
  content_nodes ||--o{ content_edges : from
  content_nodes ||--o{ content_edges : to
  impact_events ||--o{ impact_items : lists
  content_nodes ||--o{ impact_items : affected
  profiles ||--o{ content_opportunities : receives
```

## 4. Indexes & RLS
- Index: FK columns; `assets(owner_id,kind,status)`; `content_edges(from_node)`, `(to_node)`; HNSW on embeddings (cosine); `jobs(input_hash)`.
- RLS: owner policy on every table with `owner_id`; child tables join through parent (or carry denormalized `owner_id`—we denormalize on `scenes`, `transcript_segments`, `content_*`, `impact_*` for speed).
- Storage policies by path prefix `{user_id}/`.

## 5. Retention
Original media retained until user deletes; derived artifacts (frames, audio) deleted after 30 days or on asset delete; transcripts kept with asset; `skill_runs.output` redacted of raw media references; account deletion cascades.
