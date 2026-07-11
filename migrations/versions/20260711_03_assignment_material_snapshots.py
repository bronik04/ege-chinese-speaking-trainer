"""Store immutable material snapshots on assignments."""

from alembic import op

revision = "20260711_03"
down_revision = "20260706_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE assignments ADD COLUMN IF NOT EXISTS material_snapshot_json TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE assignments DROP COLUMN IF EXISTS material_snapshot_json")
