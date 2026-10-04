# UX Specification

Conventions: components reference `DESIGN-SYSTEM.md` (Button, Card, Badge, Stepper, Modal). API paths reference `API-SPECIFICATION.md`. Global **Empty/Error** pattern from the design system applies unless overridden. Default responsive rule: <640 single column; ≥1024 rail + main (+ inspector).

Global shell (all project screens): left **Workflow Rail** (blueprint stages as Stepper), top bar (project title, Asset Library button, status badges), main canvas. Only stages in the active blueprint appear.

---
## 1. Landing / Create
- **Purpose:** capture intent. **Goal:** say what I want to make with zero learning.
- **Layout:** asymmetric: giant headline "What do you want to create today?" left; stacked card right with fields. No nav tools, no feature grid.
- **Components:** Input (required) "What do you want to create today?"; Textarea (optional) "Tell us more"; example chips (click fills); Button primary lg "Build My Creation Plan"; small link "Try the demo project".
- **Interactions:** submit disabled until required field ≥ 5 chars; Enter in field 1 focuses field 2; chip fills.
- **States:** idle, submitting (button shows purple stripe), error (coral inline).
- **Animations:** headline words stagger in; button spec press; page transition to screen 2.
- **API:** `POST /api/creation/intents`. 
- **Responsive:** stacked. **Empty:** n/a. **Error:** "Couldn't understand that — try adding a format or platform." + Retry.

## 2. Intent Processing
- **Purpose:** show understanding, allow correction. **Goal:** confirm interpretation.
- **Layout:** left: original text; right: "Here's what we heard" Card ai with chips for content_type, format, platform, duration, tone, style, audience, expected output; below: assumptions list with confidence badges.
- **Components:** editable chips (popover select), Button "Looks right → Build Blueprint", Button secondary "Edit details".
- **Interactions:** chip edit updates intent draft; low-confidence (<0.6) chips highlighted cyan with "Is this right?".
- **States:** analyzing (skeleton chips appearing one by one), ready, failed.
- **Animations:** chips pop in sequentially (0.08 s stagger).
- **API:** `GET /api/creation/intents/:id`, `PATCH /api/creation/intents/:id`, `POST /api/creation/blueprints`.
- **Responsive:** chips wrap. **Empty:** n/a. **Error:** fallback to manual form with same fields.

## 3. Creation Blueprint
- **Purpose:** present the dynamic workflow. **Goal:** understand and approve the plan.
- **Layout:** vertical numbered stage list (the 16 dance stages, for example) as large cards; each shows stage name, skill badges, expected output, status badge (REAL/MOCKED/...); right inspector: required assets checklist + expected output summary.
- **Components:** stage Card, Badge, Button primary "Start Creating", Button ghost "Remove stage", "Add stage" menu (lists compatible skills).
- **Interactions:** reorder via drag (keyboard alternative), toggle optional stages, click stage → opens its workspace.
- **States:** generating (stages stagger in), ready, edited.
- **Animations:** staggered entrance; layout animation on reorder.
- **API:** `GET /api/blueprints/:id`, `PATCH /api/blueprints/:id`, `POST /api/projects/:id/workflows`.
- **Responsive:** inspector moves below. **Empty:** n/a. **Error:** "Blueprint failed" + regenerate; fall back to generic workflow template.

## 4. Project Workspace
- **Purpose:** home base for a project. **Goal:** see progress, next action.
- **Layout:** header with "Next best action" Card (lime); stage grid with statuses; recent asset strip; activity feed.
- **Components:** progress bar, stage tiles, Asset strip.
- **Interactions:** click tile → stage workspace; "Run all ready stages".
- **States:** new, in progress, done. **Empty:** "Nothing yet — start with Concept." **Error:** failed stage tile coral with Retry.
- **API:** `GET /api/projects/:id`, `GET /api/projects/:id/workflows`.

## 5. Script Workspace
- **Purpose:** concept, hooks, script, captions, CTA. **Goal:** pick and edit a script I'd actually say/perform.
- **Layout:** left: hook options (3–5 cards with style label); center: script editor (lines with beat numbers); right: CTA + caption/title/description + Creator DNA match badge.
- **Components:** Card ai, Textarea per line, Button "Use this hook", "Regenerate", version selector.
- **Interactions:** select hook inserts at line 1; edit line → debounced save creating `script_versions`; edit triggers Impact Propagation check when dependents exist.
- **States:** generating, ready, editing, saving, conflict.
- **Animations:** hooks slide in staggered; accepted hook "stamps" with spring.
- **API:** `POST /api/scripts/generate`, `POST /api/hooks/generate`, `PATCH /api/scripts/:id`, `GET /api/scripts/:id/versions`.
- **Empty:** "Generate your first hook." **Error:** retry; keep prior version.

## 6. Reference Workspace
- **Purpose:** find/analyze a reference. **Goal:** borrow structure, not content.
- **Layout:** left: add reference (upload file / paste URL / pick from suggestions); center: player + **Reference DNA** card (duration, hook duration, shot count, avg shot length, framing, movement, transitions, rhythm, captions, CTA, pacing); right: "Apply to my plan" with diff of what changes.
- **Components:** Card media, mini shot-length bar chart, Badge `inspired-by`, attribution field, Button "Create inspired plan".
- **Interactions:** analyze → progress; toggle which DNA traits to apply.
- **States:** empty, analyzing, ready, unsupported URL.
- **API:** `POST /api/references`, `POST /api/references/analyze`, `GET /api/references/:id/dna`.
- **Empty:** "Add a reference you like." **Error:** "We can't fetch that URL — upload the file instead."

## 7. Shot Planner
- **Purpose:** AI Creative Director recording plan. **Goal:** know exactly how to shoot.
- **Layout:** vertical list of Shot cards (SHOT 01…): duration, camera (framing), distance, camera height, action, lighting, background, notes; top: total duration meter; right: checklist (props, space, lighting).
- **Components:** Shot Card (editable fields), diagram placeholder (simple SVG of camera position), Button "Regenerate shot", "Export shot list".
- **Interactions:** edit fields; drag reorder; durations auto-sum with warning if ≠ target.
- **States:** generating, ready, edited.
- **API:** `POST /api/shots/plan`, `PATCH /api/shots/:id`.
- **Empty/Error:** as global; fallback template shots for the content type.

## 8. Recording / Asset Upload
- **Purpose:** bring footage and assets in. **Goal:** upload once, see processing.
- **Layout:** big dropzone; upload list with per-file progress; asset library tabs (Video, Image, Audio, Script, Reference, Brand).
- **Interactions:** drag-drop, multi-file; tag asset type; map upload to shot (optional).
- **States:** idle, uploading, validating, processing, ready, rejected (type/size).
- **Animations:** file chips drop in; progress bar.
- **API:** `POST /api/assets/upload-url`, `POST /api/assets/complete`, `GET /api/assets`.
- **Error:** rejected file shows reason ("MP4/MOV up to 200 MB").

## 9. Video Understanding
- **Purpose:** show what the AI sees/hears. **Goal:** trust matching.
- **Layout:** player top; below: synced transcript (words clickable), scene strip with keyframe thumbnails + captions; right: **Script ↔ Footage** matrix (script lines vs timestamp ranges with confidence).
- **Interactions:** click line → seek; drag to re-assign match; mark match wrong.
- **States:** processing stages checklist; ready; partial (transcript failed → visual-only).
- **API:** `POST /api/video/analyze`, `GET /api/video/:assetId/analysis`, `GET /api/jobs/:id`.
- **Empty:** "Upload footage to analyze." **Error:** per-stage retry.

## 10. AI Editing Workspace
- **Purpose:** clip review + edit suggestions. **Goal:** accept/modify, export.
- **Layout:** top: clip candidates list (score, reason, confidence); center: preview (9:16 frame overlay) ; bottom: timeline (video, captions, music suggestion, B-roll suggestion); right inspector: suggestion list with Apply/Dismiss.
- **Interactions:** trim handles, accept/reject candidate, apply suggestion (creates new EDL version; undo), export.
- **States:** suggesting, ready, rendering, exported, render failed.
- **Animations:** timeline springs; applied suggestion flashes lime.
- **API:** `POST /api/clips/generate`, `PATCH /api/clips/:id`, `POST /api/edits/suggest`, `PATCH /api/edits/:id`, `POST /api/edits/:id/render`.
- **Error:** render failure shows FFmpeg stage; EDL preserved.

## 11. Content Genome
- **Purpose:** show relationships. **Goal:** see what depends on what.
- **Layout:** graph canvas (left→right layers: Idea → Script → Footage → Clips → Variants → Published); right inspector: node detail, dependents, version history; top: "Edit impact simulator".
- **Interactions:** click node highlights ancestors/descendants; edit a script sentence in inspector → **Impact Panel** "4 content assets affected" with list (affected / text affected / possibly affected) and actions Review individually / Update all / Ignore.
- **Animations:** propagation ripple; affected nodes turn coral.
- **API:** `GET /api/content-genome/:projectId`, `POST /api/content-genome/propagate`, `POST /api/content-genome/impacts/:id/resolve`.
- **Empty:** "Your genome grows as you create." **Error:** fallback list view.

## 12. Multi-Platform Adaptation
- **Purpose:** variants per platform. **Goal:** one source → many outputs.
- **Layout:** platform tabs (Reels, Shorts, TikTok, YouTube, LinkedIn); each: spec card (aspect, duration, caption length), preview, caption/title/description/hashtags, adaptation notes.
- **Interactions:** generate, edit, mark approved.
- **API:** `POST /api/platform/adapt`, `PATCH /api/variants/:id`.
- **Status:** Reels REAL; other tabs MOCKED labelled.

## 13. Publishing
- **Purpose:** final review and handoff. **Goal:** confident publish.
- **Layout:** checklist (script approved, captions, rights/attribution, variants), per-variant "Download" and "Copy caption"; scheduler (STUBBED).
- **API:** `POST /api/publishing/jobs` (STUBBED returns export package).
- **Error:** checklist failures block with explanation.

## 14. Analytics
- **Purpose:** results. **Goal:** see what worked.
- **Layout:** KPI tiles, per-variant table, hook-performance chart.
- **Status:** MOCKED seeded data; clearly badged.
- **API:** `GET /api/analytics?projectId=`.
- **Empty:** "Publish something to see results."

## 15. Creator Intelligence
- **Purpose:** learn and recommend. **Goal:** know what to create next.
- **Layout:** top "Create next" cards (3 opportunities with reasons); Creator DNA card; patterns (repeated hooks, durations); gaps; unused-assets tile → Archaeology.
- **Interactions:** "Start this idea" prefills Landing intent.
- **API:** `GET /api/creator-intelligence`, `GET /api/creator-dna`, `GET /api/content-opportunities`.
- **Status:** MOCKED over seeded + real project data where available.

## 16. Content Archaeology
- **Purpose:** mine old assets. **Goal:** reuse what I forgot.
- **Layout:** headline "You have 47 minutes of unused footage."; opportunity breakdown (7 short-form, 3 educational, 2 social posts, 1 carousel); list of opportunity cards with source clip preview, reason, effort estimate, "Make this" button.
- **Interactions:** run scan; dismiss; "Make this" starts a pre-filled workflow.
- **API:** `POST /api/archaeology/scan`, `GET /api/content-opportunities`.
- **Status:** PARTIAL (scan on seeded library; real scan on uploaded assets stretch).
- **Empty:** "Upload older footage to scan."
