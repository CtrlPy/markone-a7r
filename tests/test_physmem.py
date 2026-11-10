import struct

import pytest

from a7r.physmem import PhysMemError, kernel_virt, pagemap_offset, parse_pagemap, ram_start


def test_pagemap_offset_is_page_index_times_8():
    assert pagemap_offset(0x06376A12) == (0x06376A12 >> 12) * 8


def test_parse_present_entry():
    entry = struct.pack("<Q", (1 << 63) | 0x834E5)
    assert parse_pagemap(entry) == 0x834E5


def test_parse_not_present_raises():
    with pytest.raises(PhysMemError, match="not present"):
        parse_pagemap(struct.pack("<Q", 0x123))


def test_parse_swapped_raises():
    with pytest.raises(PhysMemError, match="swapped"):
        parse_pagemap(struct.pack("<Q", (1 << 63) | (1 << 62) | 5))


def test_ram_start_from_iomem():
    iomem = "00000000-0000ffff : sram\n80000000-9fffffff : System RAM\n  80008000-80700000 : Kernel text\n"
    assert ram_start(iomem) == 0x80000000


def test_kernel_virt_linear_map():
    assert kernel_virt(0x834E5A12, ram=0x80000000) == 0xC34E5A12


from a7r.physmem import check_page_before_write

PAGE_BYTES = bytes(range(256)) * 16


def test_check_page_accepts_matching_page_with_original_bytes():
    page = bytearray(PAGE_BYTES)
    page[0xA12:0xA16] = bytes.fromhex("032c00d9")
    assert check_page_before_write(bytes(page), bytes(page), 0xA12, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0")) == "write"


def test_check_page_reports_already_patched():
    page = bytearray(PAGE_BYTES)
    page[0xA12:0xA16] = bytes.fromhex("022c00d0")
    file_page = bytearray(page)
    file_page[0xA12:0xA16] = bytes.fromhex("032c00d9")
    assert check_page_before_write(bytes(page), bytes(file_page), 0xA12, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0")) == "already"


def test_check_page_refuses_when_other_bytes_differ_from_file():
    page = bytearray(PAGE_BYTES)
    page[0xA12:0xA16] = bytes.fromhex("032c00d9")
    file_page = bytearray(page)
    page[0x10] ^= 0xFF
    with pytest.raises(PhysMemError, match="differs from the file"):
        check_page_before_write(bytes(page), bytes(file_page), 0xA12, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))


def test_check_page_refuses_unexpected_patch_site():
    page = bytearray(PAGE_BYTES)
    page[0xA12:0xA16] = bytes.fromhex("deadbeef")
    file_page = bytearray(page)
    with pytest.raises(PhysMemError, match="expected"):
        check_page_before_write(bytes(page), bytes(file_page), 0xA12, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))


from a7r.physmem import check_live_page_before_write


def _live_pages(site=b"\0" * 8, off=0x120):
    page = bytearray(PAGE_BYTES)
    page[off:off + len(site)] = site
    return bytes(page), off


def test_live_page_write_allowed_when_both_views_agree_and_hold_the_old_value():
    page, off = _live_pages()
    assert check_live_page_before_write(page, page, off, b"\0" * 8, b"\x01" * 8) == "write"


def test_live_page_reports_already_when_the_new_value_is_there():
    page, off = _live_pages(site=b"\x01" * 8)
    assert check_live_page_before_write(page, page, off, b"\0" * 8, b"\x01" * 8) == "already"


def test_live_page_rejects_a_frame_that_differs_from_the_process_view():
    page, off = _live_pages()
    other = bytearray(page)
    other[0x800] ^= 0xFF
    with pytest.raises(PhysMemError, match="process view"):
        check_live_page_before_write(bytes(other), page, off, b"\0" * 8, b"\x01" * 8)


def test_live_page_rejects_an_unexpected_value_at_the_site():
    page, off = _live_pages(site=b"\x07" * 8)
    with pytest.raises(PhysMemError, match="holds"):
        check_live_page_before_write(page, page, off, b"\0" * 8, b"\x01" * 8)


def test_live_page_rejects_a_site_that_crosses_the_page_end():
    page, _ = _live_pages()
    with pytest.raises(PhysMemError, match="page"):
        check_live_page_before_write(page, page, 4092, b"\0" * 8, b"\x01" * 8)
