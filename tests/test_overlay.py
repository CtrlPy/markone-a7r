import hashlib

import pytest

from a7r.overlay import OverlayError, overlay_steps, undo_steps, write_commands, run_steps

LIB = "cmn_view_processDataMgr.so"


def test_write_commands_are_exactly_mkdir_bind_and_umount():
    assert write_commands(LIB) == {
        "mkdir -p /android/a7r",
        f"mount -o bind /android/a7r/{LIB} /usr/lib/{LIB}",
        f"umount /usr/lib/{LIB}",
    }


def test_unknown_library_is_refused():
    with pytest.raises(OverlayError):
        write_commands("libc.so.6")


class FakeCamera:
    def __init__(self, maps_hit=False, corrupt=False):
        self.files = {}
        self.maps_hit = maps_hit
        self.corrupt = corrupt
        self.log = []

    def writeFile(self, path, data):
        self.log.append(("write", path))
        self.files[path] = data[:-1] + b"X" if self.corrupt else data

    def readFile(self, path):
        return self.files[path]


class FakeSession:
    def __init__(self, cam):
        self.cam = cam
        self.mounted = False

    def run(self, cmd):
        self.cam.log.append(("run", cmd))
        if cmd.startswith("grep -l"):
            return f"/proc/148/maps\n" if self.cam.maps_hit else "\n"
        if cmd.startswith("mount -o bind"):
            self.mounted = True
        if cmd.startswith("umount"):
            self.mounted = False
        if cmd == "cat /proc/mounts":
            return f"/dev/x /usr/lib/{LIB} ext2 ro 0 0\n" if self.mounted else "rootfs / rootfs rw 0 0\n"
        return "\n"


def test_overlay_writes_verifies_then_binds():
    cam = FakeCamera()
    data = b"patched-lib"
    run_steps(overlay_steps(LIB, data), FakeSession(cam), cam)
    runs = [x[1] for x in cam.log if x[0] == "run"]
    assert runs.index("mkdir -p /android/a7r") < runs.index(f"mount -o bind /android/a7r/{LIB} /usr/lib/{LIB}")
    assert ("write", f"/android/a7r/{LIB}") in cam.log


def test_overlay_aborts_if_library_already_loaded():
    cam = FakeCamera(maps_hit=True)
    with pytest.raises(OverlayError, match="already loaded"):
        run_steps(overlay_steps(LIB, b"x"), FakeSession(cam), cam)
    assert not any(x[0] == "write" for x in cam.log)


def test_overlay_aborts_before_bind_on_readback_mismatch():
    cam = FakeCamera(corrupt=True)
    with pytest.raises(OverlayError, match="sha256"):
        run_steps(overlay_steps(LIB, b"patched-lib"), FakeSession(cam), cam)
    assert not any(x[0] == "run" and x[1].startswith("mount") for x in cam.log)


def test_overlay_fails_if_mount_not_visible():
    class NoMount(FakeSession):
        def run(self, cmd):
            out = super().run(cmd)
            self.mounted = False
            return out if cmd != "cat /proc/mounts" else "rootfs / rootfs rw 0 0\n"
    cam = FakeCamera()
    with pytest.raises(OverlayError, match="not visible"):
        run_steps(overlay_steps(LIB, b"y"), NoMount(cam), cam)


def test_undo_unmounts_and_checks():
    cam = FakeCamera()
    s = FakeSession(cam)
    s.mounted = True
    run_steps(undo_steps(LIB), s, cam)
    assert not s.mounted


def test_unloaded_check_ignores_echoed_command_with_prompt_fragment():
    class EchoSession(FakeSession):
        def run(self, cmd):
            if cmd.startswith("grep -l"):
                return f"re/app # {cmd}\n"
            return super().run(cmd)
    cam = FakeCamera()
    run_steps(overlay_steps(LIB, b"z"), EchoSession(cam), cam)
