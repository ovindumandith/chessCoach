import hashlib

import pytest

from chesscoach.ingestion.storage import LocalFileStorage


def test_save_is_idempotent_and_content_addressed(tmp_path):
    storage = LocalFileStorage(tmp_path)
    data = b"1. e4 e5 *"
    sha = hashlib.sha256(data).hexdigest()
    assert storage.save(sha, data) == sha
    assert storage.save(sha, data) == sha
    assert storage.read(sha) == data


@pytest.mark.parametrize("key", ["../../etc/passwd", "ABC", "a" * 63, "../" + "a" * 61])
def test_rejects_non_sha_keys(tmp_path, key):
    with pytest.raises(ValueError):
        LocalFileStorage(tmp_path).save(key, b"x")
