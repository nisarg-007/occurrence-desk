"""linkage weights

Backs `db/linkage.py`'s scored flight-candidate query. Weights are a table, not a constant
in the SQL, for the same reason `hazard_categories.severity_weight` is a table (work pack
§2.4): a re-weighting is a dated row UPDATE, not a migration.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-09

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_WEIGHTS = {
    "date_exact": 0.60,
    "date_near": 0.20,
    "operator_hit": 0.20,
}


def upgrade() -> None:
    op.create_table(
        "linkage_weights",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("weight", sa.Numeric(4, 3), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    table = sa.table(
        "linkage_weights", sa.column("key", sa.String), sa.column("weight", sa.Numeric)
    )
    op.bulk_insert(table, [{"key": k, "weight": v} for k, v in _DEFAULT_WEIGHTS.items()])


def downgrade() -> None:
    op.drop_table("linkage_weights")
