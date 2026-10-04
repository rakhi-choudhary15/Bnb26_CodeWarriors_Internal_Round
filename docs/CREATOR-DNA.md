# Creator DNA

## 1. What it is
A compact, versioned profile of how a creator tends to create, used to personalize generation. Kept small and inspectable; the creator can view, edit, and reset it.

## 2. What is learned
| Dimension | Attributes | Source | How measured |
|---|---|---|---|
| Writing | tone tags, avg sentence length, vocabulary level, emoji use, language mix (e.g., Hinglish) | scripts, captions | stats + LLM summary |
| Hooks | hook styles (question, bold claim, story), avg hook length, repeated openings | hooks, transcripts first 3 s | clustering + counts |
| CTA | style, placement | scripts | LLM classification |
| Duration | preferred durations per platform | clips, finals | median |
| Visual | framing preference, camera style, color palette (dominant colors), lighting | keyframes | OpenCV color stats + vision caption tags |
| Editing | avg shot length, caption style, transitions used | EDLs | counts |
| Topics | topic list with frequency, recurring formats | scripts, projects | embeddings clustering |

## 3. Representation
`creator_dna.profile` JSONB, schema-validated:
```json
{
  "version": 3, "sample_count": 14,
  "writing": {"tone": ["energetic","playful"], "avg_sentence_words": 8.2, "emoji_rate": 0.4, "languages": ["en","hi"]},
  "hooks": {"styles": {"question": 0.5, "bold_claim": 0.3}, "avg_words": 9, "repeated": ["Stop scrolling if…"]},
  "cta": {"style": "soft", "examples_count": 5},
  "duration": {"instagram_reels": 28, "youtube": 540},
  "visual": {"framing": ["full_body","medium"], "palette": ["#FF6B5F","#111111"], "lighting": "natural_front"},
  "editing": {"avg_shot_s": 2.1, "caption_style": "bold_center", "transitions": ["hard_cut","whip"]},
  "topics": [{"label": "dance","freq": 0.6}],
  "confidence": {"writing": 0.7, "visual": 0.4}
}
```
Per-attribute confidence; low sample counts yield low confidence and DNA is then used softly.

## 4. Learning
- **Cold start:** short onboarding (optional) — paste 2–3 past captions/scripts or upload 1–2 videos; else defaults.
- **Implicit:** on Accept/Edit of AI output, `dna.learn` updates counters (accepted hook style, edited-out phrases). Edits are the strongest signal (diff between AI draft and final).
- **Batch:** `POST /api/creator-dna/learn` over selected assets. Update rule: exponential moving average for numbers; top-k for categorical; LLM summary regenerated only when ≥ 3 new samples.
- Bumps `version`; history retained.

## 5. Usage
- Injected as ≤ 300-token style brief into `hook.generate`, `script.generate`, `caption.generate`, `shot.plan`, `edit.suggest`.
- Scoring feature in `clip.generate` (duration/framing fit) and `hook.generate` (style fit).
- Shown in UI as "Matches your style 82%" badge with "why".
- Never overrides explicit user instruction ("Tell us more").

## 6. Privacy & Control
Stores derived stats and short phrase examples only (≤ 5 per field), not raw media. Delete/reset button. Not used for other users.

## 7. Not overengineered
No model fine-tuning. Heuristics + LLM summarization + prompts. MVP status: PARTIAL — seeded profile + live update of tone/hook/duration from the demo project; others MOCKED.
