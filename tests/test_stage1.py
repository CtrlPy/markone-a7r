import pytest

from a7r.stage1 import ALLOWED_REQUESTS, WRITABLE, parse_change, plan, unexpected_changes
from tests.bkbuilder import build_backup

ASPECT = 0x01070012


def test_parse_change_reads_hex_id_and_bytes():
    assert parse_change("0x01070012=03") == (ASPECT, b"\x03")


@pytest.mark.parametrize("bad", ["0x01070012", "01070012=zz", "=03"])
def test_parse_change_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_change(bad)


def test_plan_accepts_aspect_values_0_to_3():
    for v in range(4):
        assert plan([(ASPECT, bytes([v]))]) == {ASPECT: bytes([v])}


def test_plan_rejects_out_of_range_aspect_value():
    with pytest.raises(ValueError, match="not allowed"):
        plan([(ASPECT, b"\x04")])


def test_plan_rejects_wrong_size():
    with pytest.raises(ValueError, match="size"):
        plan([(ASPECT, b"\x03\x00")])


def test_plan_rejects_ids_outside_allowlist():
    with pytest.raises(ValueError, match="allowlist"):
        plan([(0x003E0005, b"x")])


def test_aspect_is_the_only_writable_id_for_now():
    assert set(WRITABLE) == {ASPECT}


def test_allowed_requests_have_no_bulk_backup_write():
    assert "BKDW" not in ALLOWED_REQUESTS and "PUSH" not in ALLOWED_REQUESTS and "SHEL" not in ALLOWED_REQUESTS
    assert {"BKRD", "BKWR", "BKSY", "BKDA"} <= ALLOWED_REQUESTS


def two_props(a, b):
    return build_backup([[(0, "fixed", a), (0, "fixed", b)]])


def test_unexpected_changes_ignores_planned_and_known_noise():
    before, after = two_props(b"\x01", b"\x00"), two_props(b"\x03", b"\x07")
    # id 0x00000001 is noise here; id 0 is planned
    assert unexpected_changes(before, after, planned={0: b"\x03"}, noise={1}) == []


def test_unexpected_changes_reports_other_ids_and_wrong_planned_value():
    before, after = two_props(b"\x01", b"\x00"), two_props(b"\x02", b"\x07")
    found = unexpected_changes(before, after, planned={0: b"\x03"}, noise=set())
    assert {pid for pid, _, _ in found} == {0, 1}


class FakeBackend:
    def __init__(self):
        self.sent = []

    def _req(self, cmd, data=b""):
        self.sent.append(cmd)
        return 0


def test_stage1_guard_allows_property_write_and_sync():
    from a7r.stage1 import _guard
    backend = _guard(FakeBackend())
    for cmd in (b"BKRD", b"BKWR", b"BKSY", b"BKDA"):
        backend._req(cmd)
    assert backend.sent == [b"BKRD", b"BKWR", b"BKSY", b"BKDA"]


@pytest.mark.parametrize("cmd", [b"BKDW", b"BKPR", b"PUSH", b"SHEL"])
def test_stage1_guard_refuses_bulk_and_shell(cmd):
    from a7r.stage1 import _guard
    backend = _guard(FakeBackend())
    with pytest.raises(PermissionError):
        backend._req(cmd)
