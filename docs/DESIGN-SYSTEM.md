# Neo-Brutalist Design System

Static UI = bold. Motion = purposeful. Mostly neutral base; accents carry meaning.

## 1. Color Tokens
| Token | Hex | Use |
|---|---|---|
| `--bg` | #F5F1E8 | App background |
| `--ink` | #111111 | Text, borders, shadows |
| `--white` | #FFFFFF | Cards, inputs |
| `--lime` | #C7FF4A | Primary CTA, success, "accepted" |
| `--coral` | #FF6B5F | Errors, destructive, "affected" |
| `--purple` | #6C63FF | AI activity, skills |
| `--cyan` | #59E3FF | Info, video/media, references |
| `--muted` | #6B665C | Secondary text (4.6:1 on bg) |
Rules: max 2 accent colors per screen region; accents never used as text color on `--bg` except `--ink`-outlined chips. No gradients except an optional subtle AI shimmer on purple.

## 2. Typography
- Display: **Space Grotesk** 700 (fallback system-ui). Body: **Inter** 400/500. Mono: **JetBrains Mono** (timestamps, JSON).
- Scale: 12 / 14 / 16 / 20 / 28 / 40 / 64. Headings uppercase optional for display only. Line-height 1.15 headings, 1.5 body.

## 3. Spacing, Borders, Shadows, Radii
- Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64.
- Border: `3px solid var(--ink)` (cards, buttons, inputs); dividers 2px.
- Shadows (hard, no blur): `sm 3px 3px`, `md 6px 6px`, `lg 8px 8px`, color `--ink`.
- Radii: 0 (default), 8px for chips/badges only. Asymmetric layouts: 7/5 column splits, offset cards (rotate ≤ 1°).

## 4. Components
**Button** — `Button variant=primary|secondary|danger|ghost size=sm|md|lg`
- Normal: translate(0,0), shadow 6px 6px. Hover: translate(-2px,-2px), shadow 8px 8px. Pressed: translate(3px,3px), shadow 2px 2px. Disabled: 50% opacity, no shadow. Focus-visible: 3px cyan outline offset 3px.
- Primary = lime bg; secondary = white; danger = coral.

**Input / Textarea** — white bg, 3px border, 6px 6px shadow on focus (cyan), label above in bold 14px, helper text below, error state coral border + message.

**Card** — white, 3px border, md shadow; variants: `plain`, `ai` (purple top bar), `media` (cyan top bar), `warn` (coral top bar).

**Badge** — 2px border, 8px radius, uppercase 12px. Status variants: `REAL` (lime), `MOCKED` (cyan), `STUBBED` (white dashed border), `FUTURE` (muted). Also `confidence 0.82`.

**Modal** — centered card, backdrop `rgba(17,17,17,.6)`, lg shadow, focus-trapped, Esc closes.

**Navigation** — left rail (desktop): logo block, project name, workflow step list (vertical stepper with state icons); top bar: breadcrumbs + asset library toggle. Mobile: bottom sheet stepper.

**Stepper item states:** `locked` (muted), `ready` (white), `running` (purple pulse), `needs_review` (cyan), `done` (lime check), `failed` (coral).

**Timeline** — mono timestamps, clips as chunky bordered blocks colored by type (video cyan, caption white, music purple), playhead = coral vertical bar.

## 5. States
| State | Pattern |
|---|---|
| Empty | Large outlined box, bold one-line headline, one primary action, optional sample-data link |
| Loading | Skeleton blocks with hard borders; progress bar chunky (lime fill, 3px border) |
| Error | Coral card with plain-language message, `Retry`, and expandable technical detail |
| Success | Lime badge/toast bottom-left, auto-dismiss 4 s |
| AI working | Purple card, animated "stripe" progress, step label ("Reading your reference…"), cancel button |
| AI result | Purple-bar card with `Accept` / `Edit` / `Regenerate`, confidence badge, "Why?" disclosure |
| Video processing | Cyan card, per-stage checklist (Upload → Audio → Transcript → Scenes → Index), percent bar |
| Video error | Coral card, failed stage highlighted, `Retry stage` |

## 6. Motion (Framer Motion)
| Use | Spec |
|---|---|
| Page transition | opacity 0→1, y 12→0, 0.25 s ease-out; `AnimatePresence mode="wait"` |
| Card entrance | stagger 0.06 s, spring stiffness 300 damping 28 |
| Button | `whileHover`/`whileTap` per component spec above, spring 500/30 |
| Workflow steps | layout animation on reorder; stagger reveal on blueprint generation |
| AI progress | stripe translateX loop 1.2 s linear |
| Genome propagation | ripple: affected nodes pulse coral sequentially along edges (0.15 s delay per hop) |
| Modal | scale 0.96→1 + fade 0.18 s |
| Timeline | spring on clip drag; no easing on playhead |
Honor `prefers-reduced-motion`: disable stagger/ripple, keep opacity fades only. Never animate more than 3 simultaneous independent elements.

## 7. Responsive
Breakpoints 640 / 1024 / 1280. <640: single column, stepper becomes top collapsible, shadows reduce to 4px, timeline scrolls horizontally. 640–1024: rail collapsed to icons. ≥1024: rail + main + optional right inspector (360px).

## 8. Accessibility
Contrast ≥ 4.5:1 (ink on all fills passes). Visible focus ring on all interactive elements. Don't encode state by color alone (icon + label). Keyboard: all workflow actions reachable; timeline supports arrow-key nudge. ARIA live region for AI progress. Hit targets ≥ 44px. Captions/transcripts available for all media UI. Reduced-motion respected.
