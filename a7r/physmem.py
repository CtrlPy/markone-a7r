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
