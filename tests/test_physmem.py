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
