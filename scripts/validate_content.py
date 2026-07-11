from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


class ContentValidationError(ValueError):
    """Raised when tracked content does not match its schema or repository files."""


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContentValidationError(f"{path}: {error}") from error


def _validate(document, schema: dict, path: Path) -> None:
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ContentValidationError(f"{path}:{location}: {error.message}")


def validate_repository(root: Path, *, schema_root: Path | None = None) -> None:
    root = root.resolve()
    schema_root = (schema_root or root / "schemas").resolve()
    variant_schema = _load_json(schema_root / "variant.schema.json")
    reference_schema = _load_json(schema_root / "reference-library.schema.json")

    index_path = root / "content/variants/index.json"
    index = _load_json(index_path)
    if not isinstance(index, list) or not index:
        raise ContentValidationError(f"{index_path}: expected a non-empty array")

    seen_ids: set[str] = set()
    for entry in index:
        if not isinstance(entry, dict) or set(entry) != {"id", "year", "label", "file"}:
            raise ContentValidationError(f"{index_path}: each entry must contain only id, year, label and file")
        if (
            not isinstance(entry["id"], str)
            or not isinstance(entry["label"], str)
            or not isinstance(entry["file"], str)
            or not isinstance(entry["year"], int)
            or not 2021 <= entry["year"] <= 2100
        ):
            raise ContentValidationError(f"{index_path}: invalid id, label, file or year")
        material_id = entry["id"]
        if material_id in seen_ids:
            raise ContentValidationError(f"{index_path}: duplicate id {material_id}")
        seen_ids.add(material_id)
        document_path = (root / entry["file"]).resolve()
        variants_root = (root / "content/variants").resolve()
        if variants_root not in document_path.parents:
            raise ContentValidationError(f"{index_path}: variant file escapes content/variants: {entry['file']}")
        document = _load_json(document_path)
        _validate(document, variant_schema, document_path)
        if document["id"] != material_id or document["year"] != entry["year"]:
            raise ContentValidationError(f"{document_path}: id and year must match index.json")
        for image in [
            document["tasks"]["1"]["image"],
            *document["tasks"]["2"]["images"],
            *document["tasks"]["3"]["images"],
        ]:
            image_path = (root / "public" / image).resolve()
            public_root = (root / "public").resolve()
            if public_root not in image_path.parents or not image_path.is_file():
                raise ContentValidationError(f"{document_path}: missing image {image}")

    library_path = root / "content/reference/library.json"
    library = _load_json(library_path)
    _validate(library, reference_schema, library_path)
    task_ids = [task["id"] for task in library["tasks"]]
    if task_ids != ["task-1", "task-2", "task-3"]:
        raise ContentValidationError(f"{library_path}: tasks must be task-1, task-2, task-3 in order")


def main() -> None:
    validate_repository(Path(__file__).resolve().parents[1])
    print("Content validation passed")


if __name__ == "__main__":
    main()
