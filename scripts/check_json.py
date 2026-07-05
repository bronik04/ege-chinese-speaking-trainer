from __future__ import annotations

import json
import sys
from pathlib import Path


def main(paths: list[str] | None = None) -> int:
    failures = 0
    for value in paths if paths is not None else sys.argv[1:]:
        path = Path(value)
        try:
            with path.open(encoding="utf-8") as stream:
                json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            print(f"{path}: {error}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
