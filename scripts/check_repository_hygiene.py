from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN_PATHS = {".env"}
FORBIDDEN_PREFIXES = ("var/", "backups/", "tmp/", "test-results/", "playwright-report/")
SECRET_FILENAMES = {"id_rsa", "id_ed25519"}
PRIVATE_KEY_MARKER = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")


def check_repository(root: Path, tracked_paths: list[str]) -> list[str]:
    failures: list[str] = []
    for relative in tracked_paths:
        normalized = relative.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        path = root / relative
        if normalized in FORBIDDEN_PATHS or normalized.startswith(FORBIDDEN_PREFIXES):
            failures.append(f"Tracked runtime or secret path: {relative}")
            continue
        if path.name in SECRET_FILENAMES or path.suffix.lower() == ".key":
            failures.append(f"Tracked secret key file: {relative}")
            continue
        try:
            content = path.read_bytes()
        except OSError as error:
            failures.append(f"Cannot inspect tracked file {relative}: {error}")
            continue
        if PRIVATE_KEY_MARKER.search(content):
            failures.append(f"Tracked private key content: {relative}")
    return failures


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [value.decode() for value in result.stdout.split(b"\0") if value]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures = check_repository(root, tracked_files(root))
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
