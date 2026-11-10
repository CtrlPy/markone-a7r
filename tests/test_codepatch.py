"""a7r.codepatch on synthetic data: no camera, no firmware."""
from pathlib import Path

import pytest

from a7r import codepatch
from a7r.patch import BytePatch
from a7r.physmem import PAGE

SITE = 0x90FA12
OLD, NEW = bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0")
FRAME_A, FRAME_B = 0x88BB7000, 0x88CC2000


def library():
    lib = bytearray((i * 7) & 0xFF for i in range(0x912000))
    lib[SITE:SITE + 4] = OLD
    return bytes(lib)


def patch_for(lib):
    import hashlib
    return BytePatch(name="t", file="libObj.so", sha256=hashlib.sha256(lib).hexdigest(),
                     edits=[(SITE, OLD, NEW)])


def file_page(lib):
    return lib[SITE - SITE % PAGE: SITE - SITE % PAGE + PAGE]


class FakeCamera:
    def __init__(self, pages):
        self.pages = {k: bytearray(v) for k, v in pages.items()}
        self.writes, self.drop_writes = [], False

    def _frame(self, addr):
        return addr - addr % PAGE

    def readMemory(self, addr, size):
        page = self.pages.get(self._frame(addr), bytearray(PAGE))
        off = addr % PAGE
        return bytes(page[off:off + size])

    def writeMemory(self, addr, data):
        self.writes.append((addr, bytes(data)))
        if not self.drop_writes:
            self.pages[self._frame(addr)][addr % PAGE: addr % PAGE + len(data)] = data


def noise():
    return bytes((i * 13 + 5) & 0xFF for i in range(PAGE))


def test_picks_the_candidate_frame_that_holds_the_file_page():
    lib = library()
    cam = FakeCamera({FRAME_A: noise(), FRAME_B: file_page(lib)})
    (res,) = codepatch.apply(cam, patch_for(lib), lib, [FRAME_A, FRAME_B], log=lambda _: None)
    assert res["frame"] == FRAME_B and res["action"] == "written"
    assert cam.writes == [(FRAME_B + SITE % PAGE, NEW)]


def test_writes_nothing_when_no_candidate_matches():
    lib = library()
    cam = FakeCamera({FRAME_A: noise(), FRAME_B: noise()})
    with pytest.raises(codepatch.CodePatchError, match="no candidate"):
        codepatch.apply(cam, patch_for(lib), lib, [FRAME_A, FRAME_B], log=lambda _: None)
    assert cam.writes == []


def test_a_page_that_differs_in_one_byte_outside_the_site_is_not_accepted():
    lib = library()
    page = bytearray(file_page(lib))
    page[0x10] ^= 1
    cam = FakeCamera({FRAME_A: bytes(page)})
    with pytest.raises(codepatch.CodePatchError):
        codepatch.apply(cam, patch_for(lib), lib, [FRAME_A], log=lambda _: None)
    assert cam.writes == []


def test_already_patched_page_is_left_alone():
    lib = library()
    page = bytearray(file_page(lib))
    page[SITE % PAGE: SITE % PAGE + 4] = NEW
    cam = FakeCamera({FRAME_A: bytes(page)})
    (res,) = codepatch.apply(cam, patch_for(lib), lib, [FRAME_A], log=lambda _: None)
    assert res["action"] == "already" and cam.writes == []


def test_failed_read_back_is_an_error():
    lib = library()
    cam = FakeCamera({FRAME_A: file_page(lib)})
    cam.drop_writes = True
    with pytest.raises(codepatch.CodePatchError, match="read-back"):
        codepatch.apply(cam, patch_for(lib), lib, [FRAME_A], log=lambda _: None)


def test_library_must_be_the_build_the_patch_was_made_for():
    lib = library()
    patch = patch_for(lib)
    with pytest.raises(codepatch.CodePatchError, match="sha256"):
        codepatch.apply(FakeCamera({}), patch, lib[:-1] + b"\0", [FRAME_A], log=lambda _: None)


def test_candidates_must_be_ram_pages():
    lib = library()
    with pytest.raises(Exception):
        codepatch.apply(FakeCamera({}), patch_for(lib), lib, [0xC8BB7000], log=lambda _: None)


def test_default_candidates_are_the_frames_seen_on_the_camera():
    assert codepatch.CANDIDATE_FRAMES["libObj.so"] == [0x88BB7000, 0x88CC2000]


LIBOBJ = (Path(__file__).resolve().parent.parent / "fw" / "out" / "firmware.tar_unpacked"
          / "0700_part_image" / "dev" / "nflasha15_unpacked_unpacked" / "lib" / "libObj.so")


@pytest.mark.firmware
@pytest.mark.skipif(not LIBOBJ.is_file(), reason="firmware not unpacked in fw/out")
def test_real_image_size_patch_applies_to_a_frame_holding_the_stock_page():
    from a7r.patches import PATCHES
    lib = LIBOBJ.read_bytes()
    patch = PATCHES["libobj-image-size-aspect-fallback"]
    (off, old, new), = patch.edits
    cam = FakeCamera({FRAME_A: lib[off - off % PAGE: off - off % PAGE + PAGE]})
    (res,) = codepatch.apply(cam, patch, lib, [FRAME_B, FRAME_A], log=lambda _: None)
    assert res["frame"] == FRAME_A and cam.writes == [(FRAME_A + off % PAGE, new)]
