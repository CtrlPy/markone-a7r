import hashlib

import pytest

from a7r.patch import BytePatch, PatchError, apply_patch


def make(original=b"\x00" * 16):
    return BytePatch(
        name="demo",
        file="lib.so",
        sha256=hashlib.sha256(original).hexdigest(),
        edits=[(4, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))],
    )


def test_apply_replaces_expected_bytes():
    data = bytearray(16)
    data[4:8] = bytes.fromhex("032c00d9")
    p = BytePatch("demo", "lib.so", hashlib.sha256(bytes(data)).hexdigest(),
                  [(4, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))])
    out = apply_patch(p, bytes(data))
    assert out[4:8] == bytes.fromhex("022c00d0")
    assert out[:4] == data[:4] and out[8:] == data[8:]


def test_apply_refuses_wrong_input_hash():
    with pytest.raises(PatchError, match="sha256"):
        apply_patch(make(b"\x01" * 16), b"\x00" * 16)


def test_apply_refuses_unexpected_original_bytes():
    data = b"\x00" * 16
    p = BytePatch("demo", "lib.so", hashlib.sha256(data).hexdigest(),
                  [(4, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))])
    with pytest.raises(PatchError, match="original bytes"):
        apply_patch(p, data)


def test_edit_must_keep_length():
    with pytest.raises(PatchError, match="length"):
        BytePatch("demo", "lib.so", "0" * 64, [(0, b"\x00\x00", b"\x00")])


def test_known_patch_targets_image_size_aspect():
    from a7r.patches import IMAGE_SIZE_ASPECT_FALLBACK as p
    assert p.file == "cmn_view_processDataMgr.so"
    assert p.edits == [(0x61ACE, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))]


def test_aspect_menu_unlock_patch_targets_isValueGrayedOut_result():
    from a7r.patches import LIBOBJ_ASPECT_MENU_UNLOCK as p
    assert p.file == "libObj.so"
    assert p.edits == [(0x903B98, bytes.fromhex("041e"), bytes.fromhex("0024"))]


def test_aspect_menu_full_list_patch_clears_bit_27_in_one_literal():
    from a7r.patches import CAUTIONCONFIG_ASPECT_MENU_FULL_LIST as p
    assert p.file == "CautionConfig.so"
    assert p.edits == [(0x110F5C, bytes.fromhex("0200a05c"), bytes.fromhex("0200a054"))]
