"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Created: ${create_date}
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Custom column types are rendered by autogenerate as `app.core.types.XType()`,
# but Alembic does not emit an import for them. Keeping the import in the
# template means every revision can reference them without a manual fix-up.
import app.core.types

${imports if imports else ""}
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Apply the change. Additive first (AGENTS.md rule 21): never drop a column."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Undo the change, or state plainly why it cannot be undone."""
    ${downgrades if downgrades else "pass"}
