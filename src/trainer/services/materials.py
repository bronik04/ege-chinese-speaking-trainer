from __future__ import annotations

import json
from pathlib import Path

from trainer.domain.materials import material_payload


def official_index(root: Path) -> list[dict]:
    return json.loads((root / "content/variants/index.json").read_text(encoding="utf-8"))


def official_detail(root: Path, material_id: str) -> dict | None:
    item = next((entry for entry in official_index(root) if entry["id"] == material_id), None)
    if not item:
        return None
    payload = json.loads((root / item["file"]).read_text(encoding="utf-8"))
    return {**payload, "kind": "full", "taskNumber": None, "official": True, "status": "published"}


def public_official_index(root: Path, authenticated: bool) -> list[dict]:
    entries = official_index(root)
    if not authenticated:
        entries = [entry for entry in entries if entry["id"] == "open-2026"]
    return [{**entry, "kind": "full", "taskNumber": None, "official": True, "status": "published"} for entry in entries]


def assignment_material(root: Path, database, material_id: str) -> dict | None:
    official = official_detail(root, material_id)
    if official:
        return official
    row = database.execute("SELECT * FROM materials WHERE slug = ? AND status = 'published'", (material_id,)).fetchone()
    return material_payload(dict(row)) if row else None
