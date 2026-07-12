"""Store assignment-owned copies of author material images."""

import sqlalchemy as sa
from alembic import op

revision = "20260712_04"
down_revision = "20260711_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    identifier = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "assignment_material_assets",
        sa.Column("id", identifier, primary_key=True, autoincrement=True),
        sa.Column(
            "assignment_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "assignment_material_assets_assignment_idx",
        "assignment_material_assets",
        ["assignment_id"],
    )


def downgrade() -> None:
    op.drop_index("assignment_material_assets_assignment_idx", table_name="assignment_material_assets")
    op.drop_table("assignment_material_assets")
