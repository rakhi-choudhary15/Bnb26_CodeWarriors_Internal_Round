# Workflow Engine

## 1. Concepts
- **Blueprint** — plan (stages) generated from intent. Data, editable.
- **Workflow** — executable instance of a blueprint for a project.
- **Step** — one stage bound to ≥1 skills (`workflow_steps.skill_ids`).
- **Template** — curated stage list per content type (`backend/app/modules/blueprint/templates/*.yaml`).

## 2. Template format
```yaml
key: dance_video
match: {content_types: [dance_video, dance_reel]}
stages:
  - {key: concept, title: Concept, skills: [concept.generate], optional: false}
  - {key: hook, title: Hook, skills: [hook.generate], needs: [concept]}
  - {key: script, title: Script / structure, skills: [script.generate], needs: [hook]}
  - {key: reference_discovery, title: Reference discovery, skills: [reference.search], optional: true}
  - {key: reference_analysis, title: Reference analysis, skills: [reference.analyze], optional: true}
  - {key: shot_plan, title: Shot plan, skills: [shot.plan], needs: [script]}
  - {key: recording_guidance, title: Recording guidance, skills: [recording.coach], needs: [shot_plan]}
  - {key: asset_selection, title: Asset selection, skills: [asset.recommend]}
  - {key: footage_understanding, title: Footage understanding, skills: [video.transcribe, video.understand], needs: [asset_selection]}
  - {key: clip_selection, title: Clip selection, skills: [clip.generate, match.script_footage]}
  - {key: editing, title: AI-assisted editing, skills: [edit.suggest]}
  - {key: platform_adaptation, title: Platform adaptation, skills: [platform.adapt]}
  - {key: captions, title: Caption / title / description, skills: [caption.generate]}
  - {key: review, title: Review, skills: [], manual: true}
  - {key: publish, title: Publish, skills: [publish.assist]}
  - {key: analytics, title: Analytics, skills: [intelligence.recommend]}
```
Other templates (podcast, product_ad) in the same format: podcast = topic→outline→questions→recording→transcript→highlights→clips→social posts→publish; product_ad = product understanding→audience→hook→script→shot list→product shots→B-roll→voiceover→edit→CTA→platform variants. `generic` template: concept → script → shot plan → upload → edit → adapt → publish.

## 3. Blueprint generation algorithm
1. Pick template by `intent.content_type` (exact → alias → embedding similarity to template descriptions ≥ 0.75 → `generic`).
2. LLM `blueprint.customize` receives intent + template + registry list; returns diff ops `{add|remove|reorder|retitle|set_goal}`.
3. Validator: every skill id exists; dependencies (`needs`) satisfiable; no cycles; ≤ 20 stages; platform limits respected. Invalid ops dropped (never fail the whole blueprint).
4. Persist `creation_blueprints.stages`; mark each stage `impl_status` from skill status.

## 4. Execution model
State machine per step: `locked → ready → running → needs_review → done` (+ `failed`, `skipped`). A step is `ready` when all `needs` are `done|skipped`. Running a step: engine calls `SkillRouter.run_skill` for each skill in order, passing prior outputs through the Context Manager. Generative steps end in `needs_review`; only the creator moves them to `done` (Accept). Manual steps (review) never auto-run. Video-heavy skills return a `job_id`; the step stays `running` until the job completes (webhook-less: worker updates DB; UI polls).
- **Retries:** per skill (gateway retries 2, step retry button).
- **Resumability:** all state in DB; any step re-runnable; re-running a step creates a new output version and (via Genome) may trigger Impact Propagation for dependents.
- **Branching:** optional stages can be skipped; `Add stage` offers skills whose `dependencies` are met.
- **Dynamic adaptation:** after intent edits, "Rebuild blueprint" diff shows changes; existing completed steps preserved when their keys match.

## 5. Invocation contract with skills
Engine → Router: `{skill_id, project_id, step_id, input, idempotency_key}`. Router → Engine: `{status: ok|job|error, output?, job_id?, confidence, warnings[]}`. Every skill in `AI-SKILLS.md` is registered under the same id used in templates (consistency enforced by a startup check that every template skill id exists in the registry).

## 6. Events
Emits internal events: `step.started/completed/failed`, `content.created`, `content.changed` (consumed by Genome to compute impact). Implemented as in-process function calls (no broker).

## 7. Failure modes
Skill failure → step `failed` with user-facing reason and Retry. Provider outage → fallback model, else step `failed` with `AI_UNAVAILABLE`. Invalid template → fall back to `generic`. Stale dependency → step shows "Inputs changed" badge, not auto-rerun.
