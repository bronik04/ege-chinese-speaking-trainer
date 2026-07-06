"""Add editable full variants and standalone tasks."""

from alembic import op

revision = "20260706_02"
down_revision = "20260705_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS materials (
            id BIGSERIAL PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('full','task')),
            task_number INTEGER CHECK(task_number BETWEEN 1 AND 3),
            title TEXT NOT NULL,
            year INTEGER NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','archived')),
            content_json TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL,
            published_at BIGINT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS material_assets (
            id BIGSERIAL PRIMARY KEY,
            material_id BIGINT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
            storage_key TEXT NOT NULL UNIQUE,
            mime_type TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            created_at BIGINT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS materials_owner_idx ON materials(owner_id,updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS materials_public_idx ON materials(status,year DESC)",
        "CREATE INDEX IF NOT EXISTS material_assets_material_idx ON material_assets(material_id)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS material_assets CASCADE")
    op.execute("DROP TABLE IF EXISTS materials CASCADE")
