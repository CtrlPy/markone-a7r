import pytest

from a7r.wbidrop import DROP_CMD, WbiDropError, check_partitions, run_wbidrop, wbidrop_steps

PARTITIONS = """major minor  #blocks  name

 252        0     499712 nflasha
 252        2      13312 nflasha2
 252        5      61440 nflasha5
 252        7       4096 nflasha7
"""


def test_check_partitions_accepts_60mib_nflasha5():
    check_partitions(PARTITIONS)


def test_check_partitions_rejects_wrong_size():
    with pytest.raises(WbiDropError, match="61440"):
        check_partitions(PARTITIONS.replace(" 61440 nflasha5", " 13312 nflasha5"))


def test_check_partitions_rejects_missing():
    with pytest.raises(WbiDropError):
        check_partitions(PARTITIONS.replace("nflasha5", "nflasha55"))


def test_drop_command_is_exactly_the_updater_action():
    assert DROP_CMD == "dd if=/dev/zero of=/dev/nflasha5 bs=512 count=1"


class FakeCam:
    def __init__(self, head):
        self.flash = bytearray(head)
        self.files = {}

    def readFile(self, path):
        return self.files[path]


class FakeSession:
    def __init__(self, cam, partitions=PARTITIONS):
        self.cam, self.partitions, self.cmds = cam, partitions, []

    def run(self, cmd):
        self.cmds.append(cmd)
        if cmd == "cat /proc/partitions":
            return self.partitions
        if cmd.startswith("dd if=/dev/nflasha5 of="):
            self.cam.files[cmd.split("of=")[1].split()[0]] = bytes(self.cam.flash[:512])
        elif cmd == DROP_CMD:
            self.cam.flash[:512] = bytes(512)
        return "1+0 records in\n1+0 records out\n"


def head(magic=b"WBI1"):
    return magic + bytes(range(256)) + bytes(252)


def test_run_saves_header_drops_and_verifies(tmp_path):
    cam = FakeCam(head())
    s = FakeSession(cam)
    run_wbidrop(wbidrop_steps(), s, cam, tmp_path, log=lambda m: None)
    assert (tmp_path / "wbi_head_before.bin").read_bytes() == head()
    assert cam.flash[:512] == bytes(512)
    assert s.cmds.index(DROP_CMD) < s.cmds.index("sync")


def test_run_refuses_without_wbi_magic(tmp_path):
    cam = FakeCam(head(b"XXXX"))
    s = FakeSession(cam)
    with pytest.raises(WbiDropError, match="WBI1"):
        run_wbidrop(wbidrop_steps(), s, cam, tmp_path, log=lambda m: None)
    assert DROP_CMD not in s.cmds


def test_run_refuses_on_partition_mismatch(tmp_path):
    cam = FakeCam(head())
    s = FakeSession(cam, PARTITIONS.replace(" 61440 nflasha5", " 4096 nflasha5"))
    with pytest.raises(WbiDropError):
        run_wbidrop(wbidrop_steps(), s, cam, tmp_path, log=lambda m: None)
    assert DROP_CMD not in s.cmds


def test_already_dropped_header_is_reported_not_rewritten(tmp_path):
    cam = FakeCam(bytes(512))
    s = FakeSession(cam)
    run_wbidrop(wbidrop_steps(), s, cam, tmp_path, log=lambda m: None)
    assert DROP_CMD not in s.cmds
