"""a7r.mprphys and a7r.usbwatch on synthetic data: no camera, no firmware."""
import struct

import pytest

from a7r import mprphys, usbwatch
from a7r import mprtable as m
from a7r.physmem import PAGE

PHYS = mprphys.DEFAULT_PHYS_PAGE


def expected_blocks(with_1_1=True):
    out = [(0, 0)] * 60
    for aspect in ("3:2", "16:9"):
        for i in m.aspect_indices(aspect):
            out[i] = (1_000_000 + 4096 * i, 2_000_000 + 4096 * i)
    if with_1_1:
        for i in m.aspect_indices("1:1", sizes=("L", "M", "S")):
            out[i] = (700_000 + 4096 * i, 900_000 + 4096 * i)
    return out


def camera_page(blocks=None, fill=()):
    """The heap page as the camera holds it after start-up: 1:1 blocks still zero."""
    exp = expected_blocks()
    blocks = list(blocks) if blocks is not None else [
        (0, 0) if i in m.aspect_indices("1:1", sizes=("L", "M", "S")) else exp[i] for i in range(60)]
    for i in fill:
        blocks[i] = exp[i]
    page = bytearray(b"\xa5" * PAGE)
    for i, b in enumerate(blocks):
        off = mprphys.FIRST_BLOCK + 16 * i
        struct.pack_into("<I", page, off - 4, mprphys.HEADER)
        struct.pack_into("<2I", page, off, *b)
    return bytes(page)


class FakeCamera:
    def __init__(self, page):
        self.mem = {PHYS + i: b for i, b in enumerate(page)}
        self.writes, self.reads = [], []
        self.drop_writes = False

    def readMemory(self, addr, size):
        self.reads.append((addr, size))
        return bytes(self.mem.get(addr + i, 0) for i in range(size))

    def writeMemory(self, addr, data):
        self.writes.append((addr, bytes(data)))
        if not self.drop_writes:
            for i, b in enumerate(data):
                self.mem[addr + i] = b


# --- reading the page ---

def test_page_blocks_reads_60_pairs_at_a_16_byte_stride():
    blocks = mprphys.page_blocks(camera_page())
    assert len(blocks) == 60
    assert blocks[m.jpeg_index("L", "3:2", "STD")] == expected_blocks()[m.jpeg_index("L", "3:2", "STD")]
    assert blocks[m.jpeg_index("L", "1:1", "FINE")] == (0, 0)


def test_check_page_accepts_the_start_up_state():
    assert mprphys.check_page(camera_page(), expected_blocks()) == "zero"


def test_check_page_reports_filled_blocks():
    page = camera_page(fill=[m.jpeg_index("L", "1:1", "FINE")])
    assert mprphys.check_page(page, expected_blocks()) == "mixed"


def test_check_page_rejects_a_page_whose_stock_blocks_differ():
    blocks = mprphys.page_blocks(camera_page())
    blocks[m.jpeg_index("M", "16:9", "FINE")] = (1, 2)
    with pytest.raises(mprphys.MprPhysError, match="not the estimate page"):
        mprphys.check_page(camera_page(blocks), expected_blocks())


def test_header_is_a_16_byte_glibc_chunk_in_a_thread_arena():
    assert mprphys.HEADER & ~0x7 == 16 and mprphys.HEADER & 0x1 and mprphys.HEADER & 0x4


def test_check_page_rejects_a_page_without_the_allocation_headers():
    page = bytearray(camera_page())
    struct.pack_into("<I", page, mprphys.FIRST_BLOCK + 16 * 7 - 4, 0x19)
    with pytest.raises(mprphys.MprPhysError, match="header"):
        mprphys.check_page(bytes(page), expected_blocks())


def test_check_page_rejects_a_page_of_zeros():
    with pytest.raises(mprphys.MprPhysError):
        mprphys.check_page(bytes(PAGE), expected_blocks())


def test_check_page_needs_a_whole_page():
    with pytest.raises(mprphys.MprPhysError, match="4096"):
        mprphys.check_page(camera_page()[:100], expected_blocks())


def test_check_page_needs_real_stock_values_to_compare_with():
    with pytest.raises(mprphys.MprPhysError, match="stock"):
        mprphys.check_page(bytes(PAGE), [(0, 0)] * 60)


# --- writing ---

def test_fill_writes_8_bytes_at_the_block_and_reads_them_back():
    cam = FakeCamera(camera_page())
    i = m.jpeg_index("L", "1:1", "FINE")
    (res,) = mprphys.fill(cam, PHYS, expected_blocks(), [("L", "FINE")], log=lambda _: None)
    want = struct.pack("<2I", *expected_blocks()[i])
    assert cam.writes == [(PHYS + mprphys.FIRST_BLOCK + 16 * i, want)]
    assert res["action"] == "written"
    assert mprphys.page_blocks(cam.readMemory(PHYS, PAGE))[i] == expected_blocks()[i]


def test_fill_checks_the_whole_page_again_before_writing():
    cam = FakeCamera(camera_page())
    mprphys.fill(cam, PHYS, expected_blocks(), [("L", "FINE")], log=lambda _: None)
    assert (PHYS, PAGE) in cam.reads


def test_fill_refuses_when_the_page_is_not_the_estimate_page():
    cam = FakeCamera(bytes(PAGE))
    with pytest.raises(mprphys.MprPhysError):
        mprphys.fill(cam, PHYS, expected_blocks(), [("L", "FINE")], log=lambda _: None)
    assert cam.writes == []


def test_fill_skips_a_block_that_already_holds_the_value():
    i = m.jpeg_index("L", "1:1", "FINE")
    cam = FakeCamera(camera_page(fill=[i]))
    (res,) = mprphys.fill(cam, PHYS, expected_blocks(), [("L", "FINE")], log=lambda _: None)
    assert res["action"] == "already" and cam.writes == []


def test_undo_writes_zeros_back():
    i = m.jpeg_index("L", "1:1", "FINE")
    cam = FakeCamera(camera_page(fill=[i]))
    mprphys.fill(cam, PHYS, expected_blocks(), [("L", "FINE")], undo=True, log=lambda _: None)
    assert mprphys.page_blocks(cam.readMemory(PHYS, PAGE))[i] == (0, 0)


def test_fill_stops_at_a_failed_read_back():
    cam = FakeCamera(camera_page())
    cam.drop_writes = True
    with pytest.raises(mprphys.MprPhysError, match="read-back"):
        mprphys.fill(cam, PHYS, expected_blocks(), [("L", "FINE"), ("L", "STD")], log=lambda _: None)
    assert len(cam.writes) == 1


def test_fill_refuses_without_a_1_1_estimate_in_backup():
    cam = FakeCamera(camera_page())
    with pytest.raises(mprphys.MprPhysError, match="no 1:1 estimate"):
        mprphys.fill(cam, PHYS, expected_blocks(with_1_1=False), [("L", "FINE")], log=lambda _: None)
    assert cam.writes == []


def test_fill_refuses_implausible_values():
    exp = expected_blocks()
    exp[m.jpeg_index("L", "1:1", "FINE")] = (900_000, 800_000)
    with pytest.raises(mprphys.MprPhysError, match="implausible"):
        mprphys.fill(FakeCamera(camera_page()), PHYS, exp, [("L", "FINE")], log=lambda _: None)


def test_physical_address_must_be_a_ram_page():
    for bad in (0x7FFFF000, 0x8A4B2004, 0xC8BB7000):
        with pytest.raises(mprphys.MprPhysError):
            mprphys.check_address(bad)
    mprphys.check_address(PHYS)


# --- restart detection from the laptop's kernel log ---

JOURNAL = """\
Nov 10 14:06:41.100000 fedora kernel: usb 1-3: USB disconnect, device number 44
Nov 10 14:06:41.500000 fedora kernel: usb 1-3: New USB device found, idVendor=054c, idProduct=0336, bcdDevice= 1.00
Nov 10 14:06:43.000000 fedora kernel: usb 1-3: USB disconnect, device number 45
Nov 10 14:06:53.600000 fedora kernel: usb 1-3: New USB device found, idVendor=054c, idProduct=07c2, bcdDevice= 1.00
Nov 10 14:08:41.000000 fedora kernel: usb 1-3: USB disconnect, device number 46
Nov 10 14:08:41.400000 fedora kernel: usb 1-3: New USB device found, idVendor=054c, idProduct=0336, bcdDevice= 1.00
Nov 10 14:08:42.000000 fedora kernel: usb 1-3: USB disconnect, device number 47
Nov 10 14:08:42.900000 fedora kernel: usb 1-3: New USB device found, idVendor=054c, idProduct=07c2, bcdDevice= 1.00
"""


def test_sessions_are_found_with_their_return_time():
    sessions = usbwatch.service_sessions(JOURNAL)
    assert [(s.start, round(s.back_after, 1)) for s in sessions] == [("14:06:41", 10.6), ("14:08:41", 0.9)]
    assert [s.restarted for s in sessions] == [True, False]


def test_a_session_without_return_is_open():
    journal = "\n".join(JOURNAL.splitlines()[:3]) + "\n"
    (s,) = usbwatch.service_sessions(journal)
    assert s.back_after is None and s.restarted is None


# --- minimum time in service mode ---

def test_dwell_sleeps_until_the_minimum_has_passed():
    slept = []
    mprphys.dwell(start=100.0, minimum=3.0, clock=lambda: 100.8, sleep=slept.append)
    assert slept == [pytest.approx(2.2)]


def test_dwell_does_not_sleep_after_a_long_session():
    slept = []
    mprphys.dwell(start=100.0, minimum=3.0, clock=lambda: 104.0, sleep=slept.append)
    assert slept == []


def test_default_minimum_is_as_long_as_the_sessions_that_never_failed():
    assert mprphys.MIN_SERVICE_SECONDS >= 3.0
