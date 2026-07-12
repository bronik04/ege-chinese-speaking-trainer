from __future__ import annotations

from pathlib import Path


class LocalAudioStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("Invalid storage key")
        return target

    def put(self, key: str, source: Path, content_type: str) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    def download(self, key: str, target: Path) -> None:
        source = self._path(key)
        if not source.is_file():
            raise FileNotFoundError(key)
        target.write_bytes(source.read_bytes())

    def read(self, key: str) -> bytes:
        target = self._path(key)
        if not target.is_file():
            raise FileNotFoundError(key)
        return target.read_bytes()

    def delete(self, key: str) -> None:
        target = self._path(key)
        target.unlink(missing_ok=True)
        parent = target.parent
        if parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                pass
