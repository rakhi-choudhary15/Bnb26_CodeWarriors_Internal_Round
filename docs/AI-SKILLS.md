# AI Skills Catalog

Every skill: id, purpose, input→output, deps, model, permissions, failures, validation, MVP status. Schemas are Pydantic classes in `modules/skills/<id>/schemas.py` (abbreviated here). Common: all outputs include `confidence: float (0..1)` and `warnings: list[str]`. Permission shorthand: `r:`/`w:` + table family.

| ID | Purpose | Input → Output | Deps | Model | Permissions | Key failure | Key validation | MVP |
|---|---|---|---|---|---|---|---|---|
| `intent.analyze` | Parse intent | texts (+DNA) → `CreationIntent` | — | text, json | r:dna w:intents | ambiguous → low confidence + assumptions | enums; duration within platform limit | REAL |
| `blueprint.customize` | Adapt template | intent+template → ops | intent.analyze | text, json | w:blueprints | unknown skill id | skill exists; no cycles | REAL |
| `concept.generate` | Concept/angle options | intent → 3 concepts {title, premise, why} | intent | text | w:nodes | generic output | 3 distinct (embedding sim < 0.9) | REAL |
| `hook.generate` | Hooks | intent, concept, DNA → hooks[{text,style,score,reason}] | concept | text | r:dna w:hooks | too long | ≤ 12 words spoken / ≤ 3 s est. | REAL |
| `script.generate` | Script/structure + CTA | hook, concept, shot beats, DNA → lines[{beat,text,kind}], cta | hook | text | w:scripts | length miss | est. duration within ±10% target | REAL |
| `reference.search` | Suggest references | intent → search queries + candidate links | intent | text (+web search tool) | none | no results | URLs allowlisted scheme; labelled "suggestion" | STUBBED (curated list) |
| `reference.analyze` | Reference DNA | video asset/URL → DNA JSON | asset | vision + ffmpeg metrics | r:assets w:reference_dna | unreadable video | metrics numeric & consistent (shots×avg≈duration) | REAL (uploaded file); URL = metadata only |
| `shot.plan` | Shot-by-shot plan | script, intent, Reference DNA → shots[] | script | text, json | w:shot_plans | durations ≠ target | Σduration ≈ target; fields complete | REAL |
| `recording.coach` | Recording checklist/tips | shot plan → checklist (space, lighting, props, tips per shot) | shot.plan | text | none | — | non-empty | REAL (text) |
| `asset.ingest` | Validate/probe/index asset | upload → asset meta | — | none (ffprobe) | w:assets | corrupt file | MIME sniff, size, duration | REAL |
| `asset.recommend` | Pick relevant library assets | intent, library → ranked assets | asset.ingest | embedding | r:assets | empty library | ids exist/owned | REAL (simple vector search) |
| `video.transcribe` | Word-timestamp transcript | audio → segments[{start,end,text}] | asset | stt | r:assets w:transcript | silent audio | monotonic time; ≤ duration | REAL |
| `video.understand` | Scenes + captions | video → scenes[{start,end,caption,tags,quality}] | asset | vision | w:scenes | too many frames | frame cap; times from scene detector | REAL |
| `match.script_footage` | Link script lines↔timestamps | script, transcript, scenes → matches[{line,start,end,score,method}] | video.* | embedding (+LLM rerank) | w:matches | no speech → visual/beat method | times snapped to segment/scene bounds | REAL |
| `clip.generate` | Clip candidates | asset, transcript, scenes, intent → clips[{start,end,reason,confidence,platform}] | video.* | embedding + text | w:clips | none above threshold | 0 ≤ start < end ≤ duration; duration within platform bounds; non-overlap | REAL |
| `edit.suggest` | Editable EDL + suggestions | clip, DNA → EDL, suggestions[] | clip.generate | text, json | w:edits | invalid EDL | EDL schema; ranges in clip | REAL (trim/caption/reframe); music/B-roll/transition = MOCKED |
| `caption.generate` | Captions/title/description/hashtags | script/transcript, platform, DNA → text fields | script | text | w:variants | length overflow | platform char limits | REAL |
| `platform.adapt` | Per-platform variant | node, platforms → variants | edit/script | text | w:variants | unsupported platform | spec table | Reels REAL; others MOCKED |
| `repurpose.content` | Derive posts/carousels | master script/transcript → LinkedIn post, carousel outline | script | text | w:variants,w:nodes | — | edges created | MOCKED |
| `publish.assist` | Checklist + export package | variants → package | variants | none | r:variants | missing approvals | checklist rules | STUBBED |
| `genome.propagate` | Impact analysis | change diff + graph → impact items | genome | embedding + text | r/w:genome | diff trivial | node ids valid; levels enum | REAL for seeded/linked nodes, MOCKED suggestion text where marked |
| `archaeology.scan` | Find unused assets/opportunities | library → opportunities | assets, embeddings | embedding + text | r:assets w:opportunities | tiny library | source ranges valid | PARTIAL |
| `dna.learn` | Update Creator DNA | approved outputs/samples → DNA profile | — | text | r:content w:dna | too few samples → low confidence | schema; version bump | PARTIAL (heuristics + LLM summary) |
| `intelligence.recommend` | Next ideas/gaps | DNA, analytics, opportunities → recs | dna, analytics | text | r:all w:opportunities | no data | each rec has rationale | MOCKED over seeded data |

## Skill file layout
```
modules/skills/hook_generate/
  __init__.py     # @register_skill(spec)
  schemas.py      # Input/Output Pydantic
  prompt.md       # versioned prompt (front-matter: version)
  validators.py   # named rules
  skill.py        # run(input, ctx, gateway) -> Output
  tests/          # golden + validator tests
```

## Example spec: `clip.generate`
- **Algorithm:** (1) take transcript segments and scenes from `video.*`; (2) merge into candidate windows (sliding windows 15–45 s aligned to segment/scene boundaries); (3) score each = 0.35·semantic relevance to intent (embedding cosine) + 0.25·hook strength (LLM 0–1 on first 3 s text/visual) + 0.2·visual quality (sharpness/brightness/motion from OpenCV) + 0.1·completeness (starts/ends on sentence or beat boundary) + 0.1·Creator DNA fit; (4) non-max suppression of overlaps; (5) LLM writes `reason` for top-N; (6) validators clamp/drop invalid ranges. Weights are config, tuned on 3 sample videos.
- **Output:** `[{start_time, end_time, reason, confidence, target_platform, score_breakdown}]`.
- **Dance-without-speech path:** transcript weight redistributed to visual quality + motion energy + scene caption relevance; confidence capped at 0.7 and flagged.

## Adding a skill
1) create folder, 2) register spec, 3) add to a template or let users "Add stage", 4) add golden tests. No engine/router changes.
