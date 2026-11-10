"""a7r.firmup: which Backup.bin values Sony's updater keeps (synthetic data)."""
import pytest

from a7r import firmup
from a7r.backup import Property


def prop(pid, attr, data):
    return Property(pid, attr, data, len(data), None)


@pytest.mark.parametrize("option, mode", [("w", 0), ("n", 2), ("u", 4), ("r", 5)])
def test_ud_keep_backup_options_map_to_rewrite_modes(option, mode):
    assert firmup.MODES[option] == mode


@pytest.mark.parametrize("attr", [0x00, 0x08, 0x80, 0x88])
@pytest.mark.parametrize("mode", [0, 1, 2, 4, 5])
def test_unprotected_values_always_come_from_the_template(attr, mode):
    assert not firmup.kept(attr, mode)
    assert not firmup.kept(attr, mode, id1=True)


@pytest.mark.parametrize("attr", [0x04, 0x10, 0x20, 0x40, 0x60, 0x70])
def test_resettable_user_settings_are_kept_only_in_modes_1_and_5(attr):
    assert [m for m in (0, 1, 2, 4, 5) if firmup.kept(attr, m)] == [1, 5]


def test_read_only_values_are_kept_in_modes_4_and_5_or_when_id1_is_set():
    assert [m for m in (0, 1, 2, 4, 5) if firmup.kept(0x01, m)] == [4, 5]
    assert all(firmup.kept(0x01, m, id1=True) for m in (0, 1, 2, 4, 5))


def test_protected_values_are_kept_unless_the_mode_is_non_protect():
    assert [m for m in (0, 1, 2, 4, 5) if firmup.kept(0x02, m)] == [0, 1, 4, 5]


def test_merge_takes_the_template_value_unless_the_old_one_is_kept():
    template = {1: prop(1, 0x00, b"\0\0\0\0"), 2: prop(2, 0x60, b"\x01"), 3: prop(3, 0x02, b"AB")}
    old = {1: b"\x10\0\0\0", 2: b"\x03", 3: b"xy"}
    assert firmup.merge(old, template, mode=5) == {1: b"\0\0\0\0", 2: b"\x03", 3: b"xy"}
    assert firmup.merge(old, template, mode=4) == {1: b"\0\0\0\0", 2: b"\x01", 3: b"xy"}
    assert firmup.merge(old, template, mode=2) == {1: b"\0\0\0\0", 2: b"\x01", 3: b"AB"}


def test_merge_keeps_the_template_value_when_the_sizes_differ_or_the_old_value_is_missing():
    template = {1: prop(1, 0x02, b"AB"), 2: prop(2, 0x02, b"CD")}
    assert firmup.merge({1: b"xyz"}, template, mode=5) == {1: b"AB", 2: b"CD"}


def test_merge_drops_properties_that_the_template_does_not_have():
    template = {1: prop(1, 0x02, b"AB")}
    assert firmup.merge({1: b"xy", 9: b"zz"}, template, mode=5) == {1: b"xy"}
