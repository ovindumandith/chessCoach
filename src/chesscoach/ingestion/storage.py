"""Content-addressed file storage. Files are keyed by SHA-256, never by user filenames."""

import os
import re
from pathlib import Path

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class LocalFileStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path_for(self, sha256: str) -> Path:
        if not _SHA256_RE.match(sha256):
            raise ValueError("Storage key must be a lowercase SHA-256 hex digest")
        return self.root / sha256[:2] / f"{sha256}.pgn"

    def save(self, sha256: str, data: bytes) -> str:
        """Store data idempotently; returns the storage key."""
        path = self._path_for(sha256)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return sha256

    def read(self, storage_key: str) -> bytes:
        return self._path_for(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        self._path_for(storage_key).unlink(missing_ok=True)

    def exists(self, storage_key: str) -> bool:
        return self._path_for(storage_key).exists()
