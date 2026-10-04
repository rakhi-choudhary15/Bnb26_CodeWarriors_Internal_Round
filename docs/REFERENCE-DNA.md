# Reference DNA

## 1. Goal
Extract the *structure* of a reference video, never its content, then use it to inspire an original plan.

## 2. Inputs
Uploaded reference file (REAL). URL: metadata/oEmbed only; we do **not** download third-party platform video in MVP (ToS/copyright, SSRF) — user may upload a file they have rights to analyze. (D-010)

## 3. Extracted Attributes
| Attribute | Method |
|---|---|
| duration | ffprobe |
| shot count, avg/min/max shot duration, shot-length sequence | PySceneDetect (content detector) |
| hook duration | time to first scene change or first speech/beat (≤ 5 s heuristic) + LLM label of what the hook does |
| camera framing per shot | vision model on keyframe → {close, medium, full_body, wide} |
| camera movement | optical-flow magnitude/direction (OpenCV) → {static, pan, handheld, zoom} |
| transitions | cut type heuristics: hard cut vs fade (frame diff), whip (high flow blur) |
| visual rhythm | shot-length sequence + audio onset density → pacing curve |
| caption style | vision/OCR on keyframes → position, size, emphasis, language |
| structure | LLM over scene captions → beats (hook / setup / build / payoff / CTA) with timestamps |
| CTA | LLM on last 20% transcript/captions |
| pacing | shots per 10 s, speech wpm if speech |

## 4. Output schema (abridged)
```json
{"duration_s": 28.4, "hook": {"duration_s": 2.8, "type": "motion_opener"},
 "shots": {"count": 14, "avg_s": 2.0, "sequence_s": [2.8,1.9,...]},
 "framing": {"full_body": 0.6, "medium": 0.3, "close": 0.1},
 "movement": {"static": 0.7, "handheld": 0.3},
 "transitions": {"hard_cut": 0.85, "whip": 0.15},
 "rhythm": {"curve": [0.4,0.6,0.9,...], "bpm_est": 118},
 "captions": {"present": true, "position": "lower_third", "style": "bold_white"},
 "structure": [{"beat":"hook","start_s":0,"end_s":2.8}, ...],
 "cta": {"present": false},
 "confidence": 0.78}
```

## 5. Using it
`shot.plan` and `script.generate` receive a *transformed* DNA: numeric constraints (hook ≤ 3 s, ~2 s average shots, mostly full body, hard cuts) plus structural beats. The UI "Apply to my plan" shows toggles per trait. The prompt forbids reusing the reference's specific choreography descriptions, dialogue, lyrics, captions text, or distinctive creative elements; output must be original.

## 6. Copyright & Attribution Safe Boundaries
- Structural facts (timings, framing) are ideas/methods, not expression; we store only those metrics + short neutral labels.
- Do not store/re-host the reference media beyond the user's own upload (private, deleted on request).
- Do not transcribe reference lyrics/dialogue into outputs; transcripts of references are not persisted beyond analysis.
- Persist `creator_attribution` + source URL for provenance; UI shows "Inspired by structure of: <title/creator>" in the project (not in published copy by default; optional toggle).
- No face/voice cloning, no reuse of music/footage from the reference; music suggestions come from royalty-free categories.
- User attests rights for uploaded references (checkbox, logged).
- Not legal advice; documented in the UI help text.

## 7. Failure modes
Low-quality/very short video → reduced metrics + low confidence; very long → reject (> 3 min); unreadable → error with re-upload option.
