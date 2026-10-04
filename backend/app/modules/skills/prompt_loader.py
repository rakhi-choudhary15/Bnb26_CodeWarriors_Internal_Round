"""Prompt loading with front-matter versions (AI-ARCHITECTURE.md §10).

Prompts live in `app/ai/prompts/` in the real layout; this loader also accepts
`prompt.md` inside a skill folder, which is the layout AGENTS.md §11 prescribes.
The version is recorded on `skill_runs` so a prompt change is auditable.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.core.errors import NotFoundError

PROMPT_ROOTS = (
    Path(__file__).resolve().parents[2] / "ai" / "prompts",
    Path(__file__).resolve().parent,
)

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@lru_cache(maxsize=128)
def load_prompt(relative: str) -> str:
    """Return the prompt body with front-matter stripped."""
    body, _ = load_prompt_with_version(relative)
    return body


@lru_cache(maxsize=128)
def load_prompt_with_version(relative: str) -> tuple[str, str]:
    name = relative if relative.endswith(".md") else f"{relative}.md"
    for root in PROMPT_ROOTS:
        candidate = root / name
        if candidate.is_file():
            return _split(candidate.read_text("utf-8"))
    raise NotFoundError(
        "Prompt file not found.",
        details={"prompt": relative, "searched": [str(r) for r in PROMPT_ROOTS]},
    )


def _split(text: str) -> tuple[str, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return text.strip(), "1"
    version = "1"
    for line in match.group(1).splitlines():
        if line.lower().startswith("version:"):
            version = line.split(":", 1)[1].strip()
    return text[match.end() :].strip(), version


def clear_cache() -> None:
    load_prompt.cache_clear()
    load_prompt_with_version.cache_clear()