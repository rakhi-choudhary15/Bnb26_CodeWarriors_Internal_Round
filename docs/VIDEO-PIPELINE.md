# Video Pipeline

All media work is asynchronous in RQ workers; API only enqueues.

## 1. Stages (`video.analyze` job)
| # | Stage | What / How | Input → Output | Failure & validation |
|---|---|---|---|---|
| 0 | Ingest | download from Storage; `ffprobe` JSON; MIME sniff (libmagic); limits: ≤ 200 MB, ≤ 3 min MVP, codecs h264/hevc/vp9, resolution ≤ 4K | file → meta | reject w/ reason; corrupt → `failed` |
| 1 | Proxy | `ffmpeg` transcode to 720p h264 + aac for preview/analysis | → proxy.mp4 | retry once |
| 2 | Audio | `ffmpeg -vn -ac 1 -ar 16000` → wav | → audio.wav | no audio track → skip STT, flag `no_speech` |
| 3 | Transcribe | Whisper-compatible STT (word timestamps, language auto) | wav → segments | empty → `no_speech`; timestamps monotonic & ≤ duration |
| 4 | Scenes | PySceneDetect content detector (threshold tuned) + min length 0.8 s | proxy → scenes[start,end] | none found → fixed 3 s windows |
| 5 | Keyframes | middle frame per scene (max 40; downsample to 512 px) via ffmpeg | → jpgs | cap enforced |
| 6 | Visual captions | vision model: short caption, tags (shot type, action, setting), quality hints; batched | keyframes → caption JSON | invalid JSON → retry/repair; fallback caption "unknown" |
| 7 | Quality metrics | OpenCV: Laplacian variance (sharpness), mean luminance, motion energy (frame diff/optical flow sampled) | frames → metrics | — |
| 8 | Segment & embed | segments = transcript sentences merged to ≥ 3 s; scenes captions; embed both via gateway → `transcript_segments`, `scenes`, `asset_embeddings` | → vectors | batch size 64; retry |
| 9 | Match | if `script_id`: for each script line embed → top-k segments/scenes (cosine) → LLM rerank → `script_footage_matches` with `method`; no speech → visual/beat method | → matches | below 0.35 score = unmatched |
| 10 | Complete | update `video_analyses.status`, genome nodes (footage, scenes) | | |

Progress = completed stages/10 stored in `jobs`. Each stage is idempotent and cached by (asset hash, stage, params); retrying resumes at failed stage.

## 2. Clip generation (`clips.generate` job)
Detailed algorithm in `AI-SKILLS.md` (`clip.generate`): candidate windows aligned to boundaries → scoring (relevance, hook strength, visual quality, completeness, DNA fit) → NMS → reasons → validation. Output stored in `clips` with source timestamps preserved (`start_s/end_s` always relative to the original asset). Creator review: accept/reject/trim.

## 3. Edit model (EDL)
```json
{"version":2,"aspect":"9:16","clip_id":"…",
 "tracks":{
  "video":[{"src_asset":"…","in_s":12.0,"out_s":38.5,"reframe":{"mode":"center|follow","x":0.5,"y":0.5,"zoom":1.0}}],
  "captions":[{"start_s":0.2,"end_s":2.1,"text":"…","style":"bold_center"}],
  "markers":[{"t":0.0,"type":"transition","name":"hard_cut"}]},
 "suggestions":[{"id":"s1","type":"broll|music|transition|trim|caption|reframe","detail":"…","confidence":0.7,"applied":false}]}
```
Edits stay editable: EDL is the source of truth; renders are derived artifacts. Every change creates a new EDL version (undo).

## 4. Reframing to 9:16
Default center crop on 16:9 sources; "follow" mode: sample person/main-subject bbox every 0.5 s (vision model or OpenCV face/person detector, smoothed with moving average, clamped velocity) → ffmpeg `crop` with expression/keyframes. Vertical sources: pass-through (scale/pad to 1080×1920). MVP: center + simple subject-follow if detector works (fallback center).

## 5. Render
`ffmpeg`: trim (`-ss/-to` with re-encode for frame accuracy), crop/scale to 1080×1920, burn captions (ASS subtitles generated from EDL; font bundled), audio loudnorm, h264 `-crf 20 -preset veryfast`, `-movflags +faststart`. Output to `renders` bucket, new `assets` row (`kind=video`), linked as `variant`/`edit` node. Timeout 5 min; failure keeps EDL.

## 6. Music/B-roll suggestions
MVP: text suggestions (genre/BPM/mood from reference rhythm and tone; B-roll ideas from script lines with no strong footage match) — MOCKED. No auto-adding licensed music. Library of royalty-free tracks is FUTURE.

## 7. Isolation & Safety
Worker runs ffmpeg/ffprobe with: no network (other than gateway/storage calls from Python), per-job temp dir (cleaned), CPU/time limits (`timeout`), no shell interpolation (argument arrays), output size cap. See `SECURITY.md`.

## 8. Failure modes
Unsupported codec → clear message; STT failure → visual-only mode; vision failure → transcript-only; both → asset available but "Understanding unavailable"; render failure → retry with software encode.
