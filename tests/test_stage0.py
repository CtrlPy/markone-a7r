import hashlib
import json

import pytest

from a7r.stage0 import ALLOWED_REQUESTS, check_backup, write_manifest
from tests.bkbuilder import build_backup


def model_backup(name=b"ILCE-7R"):
    # model name lives at property 0x003e0005: subsystem 0x3e, index 5
    subsystems = [[] for _ in range(0x3E)] + [[None] * 5 + [(0, "fixed", name.ljust(16, b"\0"))]]
    return build_backup(subsystems)


def test_check_backup_accepts_matching_model():
    info = check_backup(model_backup(), expected_model="ILCE-7R")
    assert info["model"] == "ILCE-7R"
    assert info["properties"] == 1


def test_check_backup_rejects_other_model():
    with pytest.raises(ValueError, match="ILCE-7S"):
        check_backup(model_backup(b"ILCE-7S"), expected_model="ILCE-7R")


def test_check_backup_rejects_corrupt_image():
    img = bytearray(model_backup())
    img[-1] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        check_backup(bytes(img), expected_model="ILCE-7R")


def test_manifest_records_size_and_sha256(tmp_path):
    (tmp_path / "Backup.bin").write_bytes(b"abc")
    manifest = write_manifest(tmp_path, {"serial": "03377181"})
    data = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert data == manifest
    assert data["files"]["Backup.bin"] == {"size": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    assert data["meta"]["serial"] == "03377181"
    assert "SHA256SUMS" in {p.name for p in tmp_path.iterdir()}


def test_only_read_requests_are_allowed():
    assert ALLOWED_REQUESTS == {"TEST", "BKST", "BKDA", "PULL", "EXIT"}


class FakeBackend:
    def __init__(self):
        self.sent = []

    def _req(self, cmd, data=b""):
        self.sent.append(cmd)
        return 0


@pytest.mark.parametrize("cmd", [b"BKWR", b"BKDW", b"BKPR", b"PUSH", b"SHEL", b"AMNT"])
def test_guard_blocks_write_and_shell_requests(cmd):
    from a7r.stage0 import _guard
    backend = _guard(FakeBackend())
    with pytest.raises(PermissionError, match=cmd.decode()):
        backend._req(cmd)
    assert backend.sent == []


def test_guard_passes_read_requests():
    from a7r.stage0 import _guard
    backend = _guard(FakeBackend())
    for cmd in (b"TEST", b"BKDA", b"PULL", b"EXIT"):
        backend._req(cmd)
    assert backend.sent == [b"TEST", b"BKDA", b"PULL", b"EXIT"]
