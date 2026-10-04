# MVP Scope

**Primary demo:** "I want to create a 30-second energetic dancing video for Instagram."

Legend: **REAL** works end-to-end on real data. **MOCKED** UI + plausible but pre-seeded/canned data. **STUBBED** endpoint/UI exists, returns placeholder, no real action. **FUTURE** not built.

| # | Capability | Status | Notes |
|---|---|---|---|
| 1 | Intent input (2 fields + CTA) | REAL | |
| 2 | Intent understanding | REAL | LLM + validation |
| 3 | Dynamic workflow/blueprint | REAL | templates + LLM customization |
| 4 | Hook & script, CTA, captions | REAL | |
| 5 | Reference analysis (uploaded file) | REAL | ffmpeg/OpenCV metrics + vision/LLM labels |
| 5b | Reference URL analysis | STUBBED | metadata only; upload recommended |
| 5c | Reference discovery/search | STUBBED | curated list |
| 6 | Shot plan + recording guidance | REAL | |
| 7 | Video upload + validation | REAL | ≤ 200 MB / 3 min |
| 8 | Transcription | REAL | silent dance track → no_speech path shown honestly |
| 9 | Script ↔ footage matching | REAL | visual/beat fallback when no speech |
| 10 | Clip generation | REAL | |
| 11 | AI edit suggestions: trim, captions, reframe | REAL | |
| 11b | Music, B-roll, transition suggestions | MOCKED | text only |
| 12 | 9:16 export | REAL | |
| 13 | Content Genome graph | REAL (graph of demo project) | built by skills |
| 14 | Impact Propagation | REAL for text/linked nodes; LLM suggestions partly cached | video fixes = flagged tasks |
| 15 | Creator DNA | PARTIAL: seeded profile + live updates for tone/hooks/duration | |
| 16 | Content Archaeology | PARTIAL: scan over seeded library, real queries for unused minutes; opportunities partly canned | |
| 17 | Creator Intelligence | MOCKED over seeded analytics | badge visible |
| 18 | Platform variants | Reels REAL; Shorts/TikTok/YouTube/LinkedIn MOCKED | |
| 19 | Publishing | STUBBED | export package only |
| 20 | Analytics | MOCKED | |
| 21 | Auth, RLS | REAL | |
| – | Real social publishing/analytics APIs, collaboration, billing, timeline pro-editor, licensed music, AV scanning | FUTURE | |

## Cut order if time runs out (first to cut)
Archaeology live scan → Creator Intelligence real data → subject-follow reframe (use center crop) → Impact LLM (use cached) → reference analysis (use pre-analyzed reference).

## Demo safety nets
Pre-analyzed sample project; response cache; backup screen recording; offline-capable seeded data.
