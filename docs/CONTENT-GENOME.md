# Content Genome & Impact Propagation

## 1. Purpose
A typed dependency graph of everything the creator makes, so CreatorAI knows what derives from what.

## 2. Model
Nodes (`content_nodes`): idea, script, hook, claim, topic, footage, scene, broll, audio, asset, clip, edit, variant, published. Edges (`content_edges`, `from`=upstream → `to`=downstream): `derived_from`, `contains`, `uses`, `adapts`, `quotes`, `matches`. Each node has `content_hash`, `version`, `state` (current/stale/archived). Domain rows link 1:1 via `ref_table/ref_id`.

Example chain: Idea → Script → Footage → Clip → Reel / Short; Script → LinkedIn post; Script → Carousel. Claims are sub-nodes of scripts (extracted sentences with factual/opinion assertions) so edits can be traced to the specific claim.

## 3. Building the graph
Edges are created by skills at write time (deterministic, not inferred later): `script.generate` creates script node + claim nodes; `match.script_footage` creates `matches` edges; `clip.generate` creates `clip -derived_from-> footage`; `platform.adapt` creates `variant -adapts-> clip/script`. Manual relink UI is FUTURE.

## 4. Impact Propagation
**Trigger:** a `script_versions` save (or edit to any node with downstream edges) computes `diff(before, after)` at line level.
**Algorithm:**
1. Diff → changed lines/claims (token diff; ignore whitespace/punctuation-only edits).
2. Traverse graph downstream (BFS, depth ≤ 6) from changed nodes → candidate set.
3. For each candidate classify:
   - **affected**: node embeds the changed content (video clips/variants whose matched range overlaps the changed line via `matches` edges; captions burned from it).
   - **text_affected**: text-only derivative (LinkedIn post, caption) quoting or paraphrasing the claim.
   - **possibly_affected**: weak link (embedding similarity of node text to old claim ≥ 0.6 but no direct edge/overlap, e.g., carousel).
4. LLM `genome.propagate` (only on candidates) answers: does the semantic meaning change in a way that invalidates this node? Returns level + reason + `suggested_change` (e.g., new caption text; for video: "re-record line 3 or edit subtitle"). Trivial rewording → level downgraded/omitted.
5. Persist `impact_events` + `impact_items`; mark affected nodes `state=stale`.
**UI:** "4 content assets affected." Panel lists items with level badge (coral=affected, cyan=text, white=possible). Actions: **Review individually** (diff view, apply/skip per item), **Update all** (text-type items get suggested text as *new versions*; video items get an edit-suggestion task, not auto re-render), **Ignore** (resolved=ignored, node stays flagged until acknowledged).
Example: "AI will replace traditional education." → "AI will transform traditional education." → YouTube Master (affected), Instagram Reel (affected), YouTube Short (affected), LinkedIn Post (text affected), Carousel (possibly).

## 5. Backend logic
`genome.service.compute_impact(trigger_node_id, before, after) -> ImpactEvent` (sync for ≤ 50 nodes, else job). Idempotent by `hash(trigger, before_hash, after_hash)`. Updates never overwrite; they create `*_versions`/new edit versions and re-link edges.

## 6. Limitations (honest)
- Video content changes cannot be auto-fixed; we flag and suggest.
- Paraphrase detection is approximate (embeddings + LLM); can false-positive/negative — hence confidence + review.
- Only links created inside CreatorAI are known; externally edited files are not tracked.
- Depth/size caps; large graphs summarized.

## 7. MVP implementation strategy
REAL: graph tables, edge creation by skills, graph view, line-level diff, downstream traversal, impact list UI, resolve actions on text variants. MOCKED: LLM suggestion text can be pre-generated for the demo script; "update all" on video is a task flag. FUTURE: automatic re-render, cross-project genome, external imports.
