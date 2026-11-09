"""Helpers to reach a process page through physical / kernel-linear addresses.

/proc/<pid>/pagemap holds one little-endian u64 per virtual page: bit 63
present, bit 62 swapped, bits 0-54 page frame number (kernel 3.0 layout).
The kernel linear map places RAM at 0xC0000000 (PAGE_OFFSET) starting from the
first "System RAM" range in /proc/iomem.
"""
import re
import struct

PAGE = 4096
PAGE_OFFSET = 0xC0000000


class PhysMemError(Exception):
    pass


def pagemap_offset(vaddr):
    return (vaddr // PAGE) * 8


def parse_pagemap(entry):
    (v,) = struct.unpack("<Q", entry)
    if v & (1 << 62):
        raise PhysMemError("page is swapped")
    if not v & (1 << 63):
        raise PhysMemError("page not present")
    return v & ((1 << 55) - 1)


def ram_start(iomem):
    for line in iomem.splitlines():
        m = re.match(r"^([0-9a-f]+)-[0-9a-f]+ : System RAM$", line.strip())
        if m:
            return int(m.group(1), 16)
    raise PhysMemError("no System RAM in /proc/iomem")


def kernel_virt(phys, ram):
    return phys - ram + PAGE_OFFSET


def check_page_before_write(mem_page, file_page, page_off, old, new):
    """Decide whether a physical page may be patched.

    The whole page must equal the file page except the patch site, which must
    hold either the original bytes ("write") or the replacement ("already").
    """
    if len(mem_page) != PAGE or len(file_page) != PAGE:
        raise PhysMemError("page size mismatch")
    end = page_off + len(old)
    if mem_page[:page_off] != file_page[:page_off] or mem_page[end:] != file_page[end:]:
        raise PhysMemError("memory page differs from the file page outside the patch site; wrong frame")
    site = mem_page[page_off:end]
    if site == old:
        return "write"
    if site == new:
        return "already"
    raise PhysMemError(f"patch site holds {site.hex()}, expected {old.hex()}")
