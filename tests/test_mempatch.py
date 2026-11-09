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


POKE = b"\x7fELF-fake-a7rpoke"


def test_steps_use_a7rpoke_with_absolute_address():
    steps = mempatch_steps(PATCH, pid=148, base=0x05A67000, poke=POKE)
    addr = 0x05A67000 + 0x90FA12
    cmds = [s[1] for s in steps if s[0] in ("run", "read", "poke")]
    assert f"/android/a7r/a7rpoke /proc/148/mem {addr} --read 4" in cmds
    assert f"/android/a7r/a7rpoke /proc/148/mem {addr} 032c00d9 022c00d0" in cmds
    assert "chmod 755 /android/a7r/a7rpoke" in cmds


class FakeCam:
    def __init__(self, mem, corrupt_upload=False):
        self.mem = mem
        self.files = {}
        self.corrupt_upload = corrupt_upload

    def writeFile(self, p, d):
        self.files[p] = d + b"!" if self.corrupt_upload else d

    def readFile(self, p):
        return self.files[p]


class FakeSession:
    def __init__(self, cam):
        self.cam, self.cmds = cam, []

    def run(self, cmd):
        self.cmds.append(cmd)
        parts = cmd.split()
        if parts[0] == "/android/a7r/a7rpoke":
            if parts[3] == "--read":
                return f"re/app # {cmd}\nread {self.cam.mem.hex()}\n"
            old, new = bytes.fromhex(parts[3]), bytes.fromhex(parts[4])
            out = f"before {self.cam.mem.hex()}\n"
            if self.cam.mem == new:
                return out + "already patched\n"
            if self.cam.mem != old:
                return out + "contents differ from expected original, nothing written\n"
            self.cam.mem[:] = new
            return out + f"after {self.cam.mem.hex()}\nok\n"
        return "\n"


def test_run_patches_and_verifies():
    cam = FakeCam(bytearray.fromhex("032c00d9"))
    run_mempatch(mempatch_steps(PATCH, 148, 0x05A67000, POKE), FakeSession(cam), cam, log=lambda m: None)
    assert cam.mem == bytearray.fromhex("022c00d0")


def test_run_refuses_unexpected_memory_contents():
    cam = FakeCam(bytearray.fromhex("deadbeef"))
    s = FakeSession(cam)
    with pytest.raises(MemPatchError, match="expected"):
        run_mempatch(mempatch_steps(PATCH, 148, 0x05A67000, POKE), s, cam, log=lambda m: None)
    assert not any(c.endswith("032c00d9 022c00d0") for c in s.cmds)


def test_run_is_idempotent_when_already_patched():
    cam = FakeCam(bytearray.fromhex("022c00d0"))
    s = FakeSession(cam)
    run_mempatch(mempatch_steps(PATCH, 148, 0x05A67000, POKE), s, cam, log=lambda m: None)
    assert not any(c.endswith("032c00d9 022c00d0") for c in s.cmds)


def test_run_aborts_if_tool_upload_is_corrupt():
    cam = FakeCam(bytearray.fromhex("032c00d9"), corrupt_upload=True)
    s = FakeSession(cam)
    with pytest.raises(MemPatchError, match="sha256"):
        run_mempatch(mempatch_steps(PATCH, 148, 0x05A67000, POKE), s, cam, log=lambda m: None)
    assert not any(c.startswith("/android/a7r/a7rpoke") for c in s.cmds)


def test_libobj_patch_matches_menu_fallback():
    from a7r.patches import LIBOBJ_IMAGE_SIZE_ASPECT_FALLBACK as p
    assert p.file == "libObj.so"
    assert p.edits == [(0x90FA12, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))]


def test_read_only_steps_never_write():
    steps = mempatch_steps(PATCH, 148, 0x05A67000, POKE, read_only=True)
    assert [s[0] for s in steps] == ["run", "put", "run", "read"]
    cam = FakeCam(bytearray.fromhex("032c00d9"))
    s = FakeSession(cam)
    run_mempatch(steps, s, cam, log=lambda m: None)
    assert cam.mem == bytearray.fromhex("032c00d9")
