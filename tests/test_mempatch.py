import pytest

from a7r.mempatch import MemPatchError, find_text_base, mempatch_steps, run_mempatch
from a7r.patch import BytePatch

MAPS = """00008000-0000d000 r-xp 00000000 fe:02 120 /usr/bin/im.elf
05a67000-06d92000 r-xp 00000000 fe:02 345 /usr/lib/libObj.so
06d92000-06d9a000 ---p 0132b000 fe:02 345 /usr/lib/libObj.so
06d9a000-06edd000 rw-p 0132b000 fe:02 345 /usr/lib/libObj.so
"""

PATCH = BytePatch("t", "libObj.so", "0" * 64, [(0x90FA12, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))])


def test_find_text_base_uses_first_rx_mapping_at_offset_zero():
    assert find_text_base(MAPS, "libObj.so") == 0x05A67000


def test_find_text_base_rejects_missing_library():
    with pytest.raises(MemPatchError, match="not mapped"):
        find_text_base(MAPS, "libfoo.so")


def test_steps_compute_absolute_decimal_address():
    steps = mempatch_steps(PATCH, pid=148, base=0x05A67000)
    addr = 0x05A67000 + 0x90FA12
    cmds = [s[1] for s in steps if s[0] in ("read", "write")]
    assert f"dd if=/proc/148/mem of=/android/a7r/mem_before.bin bs=1 skip={addr} count=4" in cmds
    assert f"dd if=/android/a7r/mem_patch.bin of=/proc/148/mem bs=1 seek={addr} count=4 conv=notrunc" in cmds


class FakeCam:
    def __init__(self, mem):
        self.mem = mem
        self.files = {}

    def writeFile(self, p, d):
        self.files[p] = d

    def readFile(self, p):
        return self.files[p]


class FakeSession:
    def __init__(self, cam, addr):
        self.cam, self.addr, self.cmds = cam, addr, []

    def run(self, cmd):
        self.cmds.append(cmd)
        if cmd.startswith("dd if=/proc/"):
            out = cmd.split(" of=")[1].split()[0]
            self.cam.files[out] = bytes(self.cam.mem)
        elif cmd.startswith("dd if=/android/a7r/mem_patch.bin"):
            self.cam.mem[:] = self.cam.files["/android/a7r/mem_patch.bin"]
        return "4+0 records in\n4+0 records out\n"


def test_run_patches_and_verifies():
    cam = FakeCam(bytearray.fromhex("032c00d9"))
    s = FakeSession(cam, 0)
    run_mempatch(mempatch_steps(PATCH, 148, 0x05A67000), s, cam, log=lambda m: None)
    assert cam.mem == bytearray.fromhex("022c00d0")


def test_run_refuses_unexpected_memory_contents():
    cam = FakeCam(bytearray.fromhex("deadbeef"))
    s = FakeSession(cam, 0)
    with pytest.raises(MemPatchError, match="expected"):
        run_mempatch(mempatch_steps(PATCH, 148, 0x05A67000), s, cam, log=lambda m: None)
    assert not any("of=/proc/" in c for c in s.cmds)


def test_run_is_idempotent_when_already_patched():
    cam = FakeCam(bytearray.fromhex("022c00d0"))
    s = FakeSession(cam, 0)
    run_mempatch(mempatch_steps(PATCH, 148, 0x05A67000), s, cam, log=lambda m: None)
    assert not any("of=/proc/" in c for c in s.cmds)


def test_libobj_patch_matches_menu_fallback():
    from a7r.patches import LIBOBJ_IMAGE_SIZE_ASPECT_FALLBACK as p
    assert p.file == "libObj.so"
    assert p.edits == [(0x90FA12, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))]
