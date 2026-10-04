# CreatorAI — Product Requirements Document

> "Tell us what you want to create. We'll build the workflow."

## 1. Executive Summary
CreatorAI is an **intent-driven creator operating system**. The creator types what they want to create ("a 30-second energetic dance Reel"); CreatorAI interprets the intent, produces a **Creation Blueprint**, composes a **dynamic workflow** from reusable **AI skills**, and guides the creator from idea to publish to analytics. Everything is editable; the creator stays in control.

Most creator AI tools help you generate or edit content. CreatorAI understands what you are trying to create and orchestrates the entire creative workflow.

> **Note on source material:** The hackathon problem statement was not included as a file in the request. Section 4 of the brief (eight feature areas) was treated as the authoritative problem statement. See `DECISIONS.md` D-001 and the Open Questions at the end of this file.

## 2. Problem
Creators juggle disconnected tools: notes for ideas, a doc for scripts, a phone for shooting, a cloud drive for footage, an editor, a captioning app, per-platform export, a scheduler, and a separate analytics tab. Consequences:
- Beginners don't know *what to shoot* or *how*.
- Footage and scripts have no machine-understood relationship.
- One master video becomes many derivatives with no dependency tracking; editing the source silently leaves derivatives stale.
- Old footage and ideas are forgotten (content waste).
- Analytics never feed back into what to create next.

## 3. Target Users & Personas
| Persona | Description | Pain | Primary value |
|---|---|---|---|
| **Aanya, beginner short-form creator** (21) | Dance/lifestyle, phone only | Doesn't know shot setup, hooks, pacing | AI Creative Director + shot plan |
| **Rohan, educator/podcaster** (34) | Long-form YouTube/podcast, LinkedIn presence | Repurposing is manual; derivatives drift | Clip generation, Content Genome, Impact Propagation |
| **Meera, small-brand social manager** (29) | Product ads, multiple platforms | Consistency, brand assets, speed | Brand assets, platform variants, Creator DNA |

## 4. Jobs-to-be-Done
1. When I have an idea, help me turn it into a concrete plan so I can start shooting today.
2. When I have long footage, find the best short moments so I don't scrub for hours.
3. When I change my message, tell me what else I must update.
4. When I have old footage, tell me what is worth reusing.
5. When I finish a piece, adapt it for each platform without redoing work.
6. Tell me what to create next based on what works for *me*.

## 5. Product Vision
An AI creative operating system where intent is the interface. Tools appear only when the workflow needs them.

## 6. Product Principles
1. **Intent first** — "Don't learn the tool. Tell the tool what you want to create."
2. **Progressive disclosure** — one box on the homepage; complexity appears per step.
3. **Creator control** — AI proposes; creator accepts, edits, or rejects. No irreversible silent edits.
4. **Explainability** — every suggestion carries a reason and confidence.
5. **Editable output** — all AI output is stored as structured, editable data.
6. **Honesty** — features are labelled REAL / MOCKED / STUBBED / FUTURE.
7. **Original, not copied** — reference analysis informs structure, never reproduces content.

## 7. Problem Statement Requirement Map
| # | Requirement | Product feature | Where in journey | Skill(s) | MVP status |
|---|---|---|---|---|---|
| 1 | Asset Management | Asset Library (video, image, audio, script, reference, creator, brand) | Workspace sidebar; Upload step | `asset.ingest`, `asset.tag` | **REAL** (video/audio/image/script); brand assets REAL-lite |
| 2 | Script & Hook Generation | Hook/Script workspace | Step 3–4 of blueprint | `hook.generate`, `script.generate`, `caption.generate` | **REAL** |
| 3 | Script-to-Video Understanding | Match view (script lines ↔ footage timestamps) | After upload | `video.transcribe`, `video.understand`, `match.script_footage` | **REAL** (transcript + frame captions) |
| 4 | Automated Clip Generation | Clip candidates with reason/confidence, creator review | After matching | `clip.generate` | **REAL** |
| 5 | AI-Assisted Editing | Edit suggestions (trim, captions, reframe 9:16, B-roll, music, transitions) as editable EDL | Edit workspace | `edit.suggest` | **REAL** trim/caption/reframe; music/B-roll/transitions **MOCKED** (suggestion text only) |
| 6 | Multi-Platform Adaptation | Platform variants (Reels, Shorts, TikTok, YouTube, LinkedIn) | Adapt step | `platform.adapt` | Reels **REAL**; others **MOCKED** (metadata/spec output) |
| 7 | Content Workflow | Dynamic workflow idea → analytics | Whole journey | Workflow Engine | **REAL** (idea→edit), publish/analytics **STUBBED** |
| 8 | Creator Intelligence | Dashboard: performance, patterns, gaps, unused assets, DNA, next ideas | Intelligence screen | `intelligence.recommend`, `dna.learn`, `archaeology.scan` | **MOCKED** over seeded data; archaeology partial |

Differentiators: Content Genome, Impact Propagation (demo **MOCKED** on seeded graph + **REAL** text-diff path in stretch), Content Archaeology, Creator DNA, Reference DNA, AI Creative Director.

## 8. User Stories (selected)
- US-1: As a creator I type "30-second energetic dance Reel" and get a blueprint in <10 s.
- US-2: As a creator I can edit the interpreted intent (platform, duration, tone) before the workflow is built.
- US-3: As a beginner I get a shot-by-shot plan with camera distance, height, action, lighting.
- US-4: As a creator I paste a reference URL or upload a reference and see its Reference DNA.
- US-5: As a creator I upload footage and see transcript, scenes, and which script lines match which timestamps.
- US-6: As a creator I review ranked clip candidates, adjust in/out points, and accept.
- US-7: As a creator I get editable edit suggestions and export a 9:16 MP4.
- US-8: As a creator I edit a script sentence and see "N content assets affected" with review/update/ignore.
- US-9: As a creator I see unused footage and opportunities from my library.
- US-10: As a creator I see what to create next with reasons.

## 9. Functional Requirements
- FR-1 Intent capture: mandatory "What do you want to create today?"; optional "Tell us more"; CTA "Build My Creation Plan".
- FR-2 Intent Engine returns structured `CreationIntent` (content_type, format, platform, duration_s, tone, style, audience, required_assets, required_skills, stages, expected_output, confidence, assumptions).
- FR-3 Blueprint generator selects a **workflow template** and customises it; unknown intents fall back to a generic composed workflow.
- FR-4 Workflow Engine executes steps through the Skill Router; steps have status, inputs, outputs, review state.
- FR-5 Asset upload with validation, async processing, signed URLs.
- FR-6 Transcription with word-level timestamps.
- FR-7 Scene detection + keyframe captioning.
- FR-8 Script↔footage matching with confidence.
- FR-9 Clip generation preserving source timestamps.
- FR-10 Edit Decision List (EDL) editable in UI; FFmpeg render to 9:16.
- FR-11 Content Genome graph with typed edges.
- FR-12 Impact Propagation: diff → affected nodes → per-node suggested update → creator action.
- FR-13 Reference DNA extraction.
- FR-14 Creator DNA profile learned from approved outputs and uploaded samples.
- FR-15 Content Archaeology scan and opportunity list.
- FR-16 Creator Intelligence dashboard.

## 10. Non-Functional Requirements
| Area | Requirement |
|---|---|
| Latency | Intent→blueprint p95 < 10 s; hook/script < 15 s; 60 s video analysis < 90 s |
| Reliability | All LLM outputs schema-validated; 2 retries; fallback model; graceful degradation |
| Security | See `SECURITY.md` |
| Privacy | Raw media private by default; signed URLs; no training on user content |
| Accessibility | WCAG 2.1 AA targets; reduced-motion support |
| Maintainability | Modular monolith; typed contracts; skills registrable without core changes |
| Cost | Target < $0.50 AI cost per demo project; log token usage |

## 11. Feature Prioritization (MoSCoW)
**Must (hackathon):** intent→blueprint; dynamic workflow UI; hook+script; shot plan; reference analysis (uploaded/URL-metadata); video upload; transcription; script↔footage match; clip candidates; basic edit suggestions; 9:16 export; neo-brutalist shell.
**Should:** Content Genome graph view; Impact Propagation on seeded + live script edits; Creator DNA card; caption generation; Reels variant.
**Could:** Content Archaeology scan on a seeded library; Creator Intelligence dashboard (mocked data); Shorts/LinkedIn variant text.
**Won't (hackathon):** real publishing to social APIs; real analytics ingestion; multi-user collaboration; billing; mobile apps; music licensing; avatar/voice cloning; real-time recording; training custom models.

## 12. MVP / Post-MVP
See `MVP-SCOPE.md`. Post-MVP: real publishing OAuth, analytics ingestion, richer genome, team workspaces, template marketplace for skills, timeline editor, Archaeology on real libraries.

## 13. Success Metrics
- Hackathon: demo completes end-to-end without manual intervention; intent→blueprint < 10 s; ≥ 80% of clip candidates judged "usable" by a human reviewer on 3 test videos; judges understand differentiators within 3 minutes.
- Product (post-launch): time-to-first-plan, % blueprints accepted without edits, clips accepted/clips proposed, workflow completion rate, weekly projects per creator, derivative-staleness issues caught.

## 14. Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Video processing slow/fails on demo day | M | H | Pre-processed fallback project; small sample video; async with progress UI |
| LLM latency / rate limits | M | H | Cached demo responses, fallback model, retries |
| Scope creep | H | H | MVP-SCOPE enforced; REAL/MOCKED labels |
| Reference video copyright | M | M | Analyze structure only; no re-hosting; attribution rules (REFERENCE-DNA.md) |
| Hallucinated clip timestamps | M | M | Timestamps derive from transcript data, not LLM generation; validator clamps to media duration |

## 15. Assumptions
- Demo footage is short (≤ 3 min, ≤ 200 MB) with speech or music.
- One model provider key with multimodal + embeddings is available.
- Dance footage has little speech; matching uses visual captions + shot-plan beats (see `VIDEO-PIPELINE.md`).

## 16. Constraints
Small team, ~48 hours, modular monolith, no extra infra beyond Supabase + Redis.

## 17. Acceptance Criteria (MVP)
1. Entering the primary demo prompt yields a blueprint containing the 16-stage dance workflow with ≥ 6 stages actionable.
2. Hook and script generated, editable, versioned.
3. Shot plan shows ≥ 5 shots with duration, camera, distance, height, action, lighting, background.
4. Uploaded video is transcribed/analyzed and shows matches with timestamps.
5. ≥ 3 clip candidates with start/end/reason/confidence; accepting one creates a clip record.
6. Edit suggestions render to a downloadable 9:16 MP4.
7. Genome view displays the project graph; changing a script sentence shows affected assets count with review/update/ignore.
8. Every non-real feature is visibly badged in the UI.

## 18. Hackathon Demo Scope
See `DEMO-SCRIPT.md`.

## OPEN QUESTIONS
1. Problem statement file missing — confirm no additional requirements.
2. Which model provider/keys will the team use? (Design is provider-agnostic.)
3. Is real social publishing expected for judging? (Assumed no.)
