import pytest

from a7r.backup import BackupError, BackupFile, diff
from tests.bkbuilder import build_backup


def sample(**kw):
    return build_backup([
        [(0x00, "fixed", b"\x01"), None, (0x74, "fixed", b"\x02\x03", b"\x09\x09")],
        [(0x01, "oversize", b"ABCDE"), (0x00, "variable", b"xy", None, 4)],
    ], **kw)


def test_parses_header_fields():
    bk = BackupFile(sample())
    assert bk.revision == 4
    assert bk.region == "UC2"
    assert bk.version == "3.20"


def test_lists_only_valid_properties_with_ids():
    bk = BackupFile(sample())
    assert sorted(bk.properties) == [0x00000000, 0x00000002, 0x00010000, 0x00010001]


def test_reads_fixed_oversize_and_variable_data():
    p = BackupFile(sample()).properties
    assert p[0x00000000].data == b"\x01"
    assert p[0x00010000].data == b"ABCDE"
    assert p[0x00010001].data == b"xy"
    assert p[0x00010001].max_size == 4


def test_reads_reset_value_when_attr_allows_reset():
    p = BackupFile(sample()).properties
    assert p[0x00000002].reset == b"\x09\x09"
    assert p[0x00000000].reset is None


def test_flags_read_only_attr():
    p = BackupFile(sample()).properties
    assert p[0x00010000].read_only
    assert not p[0x00000000].read_only


def test_parses_revision_2_tables():
    bk = BackupFile(sample(revision=2))
    assert bk.revision == 2
    assert bk.properties[0x00010000].data == b"ABCDE"


def test_rejects_bad_checksum():
    img = bytearray(sample())
    img[-1] ^= 0xFF
    with pytest.raises(BackupError, match="checksum"):
        BackupFile(bytes(img))


def test_rejects_non_backup_data():
    with pytest.raises(BackupError, match="not a backup"):
        BackupFile(b"\0" * 0x200)


def test_diff_reports_changed_added_and_removed_ids():
    a = BackupFile(sample())
    b = BackupFile(build_backup([
        [(0x00, "fixed", b"\x05"), (0x00, "fixed", b"\x07"), (0x74, "fixed", b"\x02\x03", b"\x09\x09")],
        [(0x01, "oversize", b"ABCDE"), None],
    ]))
    d = {pid: (old, new) for pid, old, new in diff(a, b)}
    assert d == {
        0x00000000: (b"\x01", b"\x05"),
        0x00000001: (None, b"\x07"),
        0x00010001: (b"xy", None),
    }
