"""Edit suggestion skill package (registers `edit.suggest`)."""

from app.modules.skills.edit_suggest import validators as _validators  # noqa: F401
from app.modules.skills.edit_suggest.skill import SPEC, EditSuggestSkill  # noqa: F401

__all__ = ["SPEC", "EditSuggestSkill"]