"""a7r.mprdump on a synthetic process image: no camera and no firmware needed."""
import struct

import pytest

from a7r import mprdump
from a7r import mprtable as m
from a7r.physmem import PAGE

MPRCTRL_BASE = 0x059BD000
LIBMPR_BASE = 0x06F11000
STILL_MGR = 0x00120010
SIZE_TABLE = 0x00121000
BLOCKS = 0x00130FB0  # the 60 blocks cross a page boundary on purpose
PHYS = 0x80000000


class FakeMemory:
    """Process memory as pages with a virtual -> physical frame map."""

    def __init__(self):
        self.pages, self.frames, self.phys_writes, self.fresh_reads = {}, {}, [], 0
        self.stale_frames = set()   # vpages whose frame read is not what the process sees
        self.drop_writes = False

    def _page(self, vpage):
        if vpage not in self.pages:
            self.pages[vpage] = bytearray(PAGE)
            self.frames[vpage] = PHYS + len(self.frames) * PAGE
        return self.pages[vpage]

    def poke(self, vaddr, data):
        for i, b in enumerate(data):
            self._page((vaddr + i) & ~(PAGE - 1))[(vaddr + i) % PAGE] = b

    def read(self, vaddr, size, fresh=False):
        self.fresh_reads += fresh
        return bytes(self._page((vaddr + i) & ~(PAGE - 1))[(vaddr + i) % PAGE] for i in range(size))

    def phys_page(self, vaddr):
        self._page(vaddr & ~(PAGE - 1))
        return self.frames[vaddr & ~(PAGE - 1)]

    def _vpage(self, paddr):
        return next(v for v, f in self.frames.items() if f == paddr & ~(PAGE - 1))

    def read_phys(self, paddr, size):
        vpage = self._vpage(paddr)
        data = bytes(self.pages[vpage][paddr % PAGE: paddr % PAGE + size])
        return bytes(b ^ 0xFF for b in data) if vpage in self.stale_frames else data

    def write_phys(self, paddr, data):
        self.phys_writes.append((paddr, bytes(data)))
        if not self.drop_writes:
            self.pages[self._vpage(paddr)][paddr % PAGE: paddr % PAGE + len(data)] = data


def expected_blocks():
    """Stock modes get distinct non-zero values, hidden aspects stay empty."""
    out = [(0, 0)] * 60
    for aspect in ("3:2", "16:9"):
        for i in m.aspect_indices(aspect):
            out[i] = (1_000_000 + 4096 * i, 2_000_000 + 4096 * i)
    return out


def camera_image(blocks=None):
    mem = FakeMemory()
    blocks = expected_blocks() if blocks is None else blocks
    mem.poke(MPRCTRL_BASE + m.MPRCTRL_MP_STILLMGR, struct.pack("<I", STILL_MGR))
    mem.poke(STILL_MGR, struct.pack("<4I", MPRCTRL_BASE + 0x39020, SIZE_TABLE,
                                    MPRCTRL_BASE + m.MPRCTRL_SSI_TABLE, m.MPRCTRL_SSI_COUNT))
    mem.poke(MPRCTRL_BASE + m.MPRCTRL_SSI_TABLE,
             struct.pack("<5I", 0, 1, MPRCTRL_BASE + m.MPRCTRL_JPEG_FF_TABLE, 60, 10))
    for i, block in enumerate(blocks):
        mem.poke(MPRCTRL_BASE + m.MPRCTRL_JPEG_FF_TABLE + 8 * i, struct.pack("<2I", 1, BLOCKS + 16 * i))
        mem.poke(BLOCKS + 16 * i, struct.pack("<2I", *block))
    mem.poke(LIBMPR_BASE + m.LIBMPR_SSI_PTR, struct.pack("<I", MPRCTRL_BASE + m.MPRCTRL_SSI_TABLE))
    mem.poke(LIBMPR_BASE + m.LIBMPR_SSI_NUM, struct.pack("<I", m.MPRCTRL_SSI_COUNT))
    mem.poke(SIZE_TABLE + 8 * 3, struct.pack("<HHI", 7360, 4912, 7360 * 4912))
    return mem


def resolve(mem):
    return mprdump.resolve(mem, MPRCTRL_BASE, LIBMPR_BASE)


def with_1_1(expected=None):
    """Expected values once Backup.bin holds 1:1 estimates (RAM still has zeros)."""
    out = list(expected or expected_blocks())
    for i in m.aspect_indices("1:1", sizes=("L", "M", "S")):
        out[i] = (700_000 + 4096 * i, 900_000 + 4096 * i)
    return out


# --- pointer chain ---

def test_resolve_follows_the_chain_to_the_60_blocks():
    snap = resolve(camera_image())
    assert snap.still_mgr == STILL_MGR
    assert snap.blocks == expected_blocks()
    assert snap.block_addrs[1] == BLOCKS + 16
    assert snap.size_rows[3] == (7360, 4912, 7360 * 4912)


@pytest.mark.parametrize("addr,value,message", [
    (MPRCTRL_BASE + m.MPRCTRL_MP_STILLMGR, 0, "mp_stillMgr is null"),
    (STILL_MGR + 8, MPRCTRL_BASE + 0x3CD00, "StillSizeInfo"),
    (STILL_MGR + 12, 20, "StillSizeInfo"),
    (LIBMPR_BASE + m.LIBMPR_SSI_PTR, 0x1234, "libmpr"),
    (LIBMPR_BASE + m.LIBMPR_SSI_NUM, 3, "libmpr"),
    (MPRCTRL_BASE + m.MPRCTRL_SSI_TABLE + 12, 59, "record 0"),
    (MPRCTRL_BASE + m.MPRCTRL_JPEG_FF_TABLE + 8 * 5, 2, "entry 5"),
    (MPRCTRL_BASE + m.MPRCTRL_JPEG_FF_TABLE + 8 * 5 + 4, 0, "entry 5"),
])
def test_resolve_stops_when_the_layout_is_not_the_expected_one(addr, value, message):
    mem = camera_image()
    mem.poke(addr, struct.pack("<I", value))
    with pytest.raises(mprdump.MprDumpError, match=message):
        resolve(mem)


def test_resolve_rejects_two_entries_that_share_a_block():
    mem = camera_image()
    mem.poke(MPRCTRL_BASE + m.MPRCTRL_JPEG_FF_TABLE + 8 * 7 + 4, struct.pack("<I", BLOCKS))
    with pytest.raises(mprdump.MprDumpError, match="share"):
        resolve(mem)


# --- comparison with the formula ---

def test_rows_name_each_block():
    rows = mprdump.rows(expected_blocks(), expected_blocks())
    assert (rows[1].size, rows[1].aspect, rows[1].quality) == ("L", "1:1", "FINE")
    assert (rows[41].size, rows[41].aspect, rows[41].quality) == ("S", "3:2", "EXFINE")


def test_stock_modes_match_when_ram_equals_the_formula():
    assert mprdump.stock_mismatches(mprdump.rows(expected_blocks(), with_1_1())) == []


def test_a_differing_stock_block_is_reported():
    ram = expected_blocks()
    i = m.jpeg_index("M", "16:9", "STD")
    ram[i] = (ram[i][0] + 1024, ram[i][1])
    bad = mprdump.stock_mismatches(mprdump.rows(ram, expected_blocks()))
    assert [r.index for r in bad] == [i]


def test_vga_and_hidden_aspects_are_not_part_of_the_stock_check():
    ram = expected_blocks()
    ram[m.jpeg_index("VGA", "3:2", "STD")] = (5, 5)
    ram[m.jpeg_index("L", "4:3", "STD")] = (5, 5)
    assert mprdump.stock_mismatches(mprdump.rows(ram, expected_blocks())) == []


@pytest.mark.parametrize("fill,state", [((), "zero"), (("L", "M", "S"), "filled"), (("L",), "mixed")])
def test_hidden_aspect_state(fill, state):
    ram, expected = expected_blocks(), with_1_1()
    for i in m.aspect_indices("1:1", sizes=fill):
        ram[i] = expected[i]
    assert mprdump.hidden_state(mprdump.rows(ram, expected), "1:1") == state


def test_hidden_state_is_unexpected_when_ram_holds_other_values():
    ram = expected_blocks()
    ram[0] = (123, 456)
    assert mprdump.hidden_state(mprdump.rows(ram, with_1_1()), "1:1") == "unexpected"


# --- planning writes ---

def test_parse_target():
    assert mprdump.parse_target("L:FINE") == ("L", "FINE")
    for bad in ("L", "XL:FINE", "L:BEST", "VGA:FINE"):
        with pytest.raises(ValueError):
            mprdump.parse_target(bad)


def test_plan_fills_one_1_1_block_with_the_formula_value():
    snap, expected = resolve(camera_image()), with_1_1()
    (w,) = mprdump.plan_writes(snap, expected, [("L", "FINE")])
    assert (w.index, w.vaddr) == (1, BLOCKS + 16)
    assert w.old == bytes(8)
    assert w.new == struct.pack("<2I", *expected[1])


def test_plan_undo_swaps_old_and_new():
    snap, expected = resolve(camera_image()), with_1_1()
    (w,) = mprdump.plan_writes(snap, expected, [("L", "FINE")], undo=True)
    assert (w.old, w.new) == (struct.pack("<2I", *expected[1]), bytes(8))


def test_plan_refuses_when_the_formula_does_not_reproduce_the_stock_blocks():
    mem = camera_image()
    mem.poke(BLOCKS + 16 * m.jpeg_index("L", "3:2", "FINE"), struct.pack("<I", 77))
    with pytest.raises(mprdump.MprDumpError, match="stock"):
        mprdump.plan_writes(resolve(mem), with_1_1(), [("L", "FINE")])


def test_plan_refuses_when_backup_has_no_1_1_estimate():
    with pytest.raises(mprdump.MprDumpError, match="no 1:1 estimate"):
        mprdump.plan_writes(resolve(camera_image()), expected_blocks(), [("L", "FINE")])


@pytest.mark.parametrize("value", [(900_000, 800_000), (1, mprdump.MAX_ESTIMATE + 1)])
def test_plan_refuses_implausible_values(value):
    expected = with_1_1()
    expected[1] = value
    with pytest.raises(mprdump.MprDumpError, match="implausible"):
        mprdump.plan_writes(resolve(camera_image()), expected, [("L", "FINE")])


def test_plan_refuses_the_same_target_twice():
    with pytest.raises(mprdump.MprDumpError, match="twice"):
        mprdump.plan_writes(resolve(camera_image()), with_1_1(), [("L", "FINE"), ("L", "FINE")])


# --- applying writes ---

def plan_one(mem, undo=False):
    return mprdump.plan_writes(resolve(mem), with_1_1(), [("L", "FINE")], undo=undo)


def test_apply_writes_through_the_physical_frame_and_reads_back_both_ways():
    mem = camera_image()
    writes = plan_one(mem)
    (res,) = mprdump.apply_writes(mem, writes, log=lambda _: None)
    assert res["action"] == "written"
    assert mem.phys_writes == [(mem.phys_page(BLOCKS + 16) + (BLOCKS + 16) % PAGE, writes[0].new)]
    assert resolve(mem).blocks[1] == with_1_1()[1]
    assert mem.fresh_reads >= 2  # before and after the write, never from a cache


def test_apply_skips_a_block_that_already_holds_the_new_value():
    mem = camera_image()
    writes = plan_one(mem)
    mem.poke(BLOCKS + 16, writes[0].new)
    (res,) = mprdump.apply_writes(mem, writes, log=lambda _: None)
    assert res["action"] == "already"
    assert mem.phys_writes == []


def test_apply_undo_restores_zeros():
    mem = camera_image()
    mprdump.apply_writes(mem, plan_one(mem), log=lambda _: None)
    undo = mprdump.plan_writes(resolve(mem), with_1_1(), [("L", "FINE")], undo=True)
    mprdump.apply_writes(mem, undo, log=lambda _: None)
    assert resolve(mem).blocks[1] == (0, 0)


def test_apply_refuses_when_the_block_holds_something_else():
    mem = camera_image()
    writes = plan_one(mem)
    mem.poke(BLOCKS + 16, struct.pack("<2I", 5, 6))
    with pytest.raises(mprdump.MprDumpError, match="holds"):
        mprdump.apply_writes(mem, writes, log=lambda _: None)
    assert mem.phys_writes == []


def test_apply_refuses_a_frame_that_is_not_the_process_page():
    mem = camera_image()
    writes = plan_one(mem)
    mem.stale_frames.add((BLOCKS + 16) & ~(PAGE - 1))
    with pytest.raises(mprdump.MprDumpError, match="process view"):
        mprdump.apply_writes(mem, writes, log=lambda _: None)
    assert mem.phys_writes == []


def test_apply_stops_at_the_first_failed_read_back():
    mem = camera_image()
    writes = mprdump.plan_writes(resolve(mem), with_1_1(), [("L", "FINE"), ("L", "STD")])
    mem.drop_writes = True
    with pytest.raises(mprdump.MprDumpError, match="read-back"):
        mprdump.apply_writes(mem, writes, log=lambda _: None)
    assert len(mem.phys_writes) == 1


# --- camera access layer ---

def test_only_the_fixed_command_shapes_are_allowed():
    ok = ["pidof im.elf", "cat /proc/148/maps", "cat /proc/uptime", "mkdir -p /android/a7r",
          mprdump.dd_cmd(148, "mem", PAGE, 0x130, 2, "mem"),
          mprdump.dd_cmd(148, "pagemap", 8, 0x130, 1, "pm")]
    assert all(mprdump.is_allowed(c) for c in ok)
    assert mprdump.dd_cmd(148, "mem", PAGE, 0x130, 2, "mem") == \
        "dd if=/proc/148/mem of=/android/a7r/mem.bin bs=4096 skip=304 count=2"
    for bad in ["dd if=/dev/zero of=/dev/nflasha5 bs=512 count=1", "rm -rf /android/a7r",
                "dd if=/proc/148/mem of=/setting/x.bin bs=4096 skip=1 count=1",
                "cat /proc/148/maps; reboot", "dd if=/android/a7r/mem.bin of=/proc/148/mem bs=1 seek=1 count=1"]:
        assert not mprdump.is_allowed(bad)


class FakeCamera:
    def __init__(self, mem):
        self.mem, self.files, self.commands = mem, {}, []

    def run(self, cmd):  # stands in for the guarded terminal session
        self.commands.append(cmd)
        words = dict(w.split("=", 1) for w in cmd.split()[1:])
        bs, skip, count = int(words["bs"]), int(words["skip"]), int(words["count"])
        if words["if"].endswith("/pagemap"):
            data = struct.pack("<Q", (1 << 63) | self.mem.phys_page(skip * PAGE) // PAGE)
        else:
            data = self.mem.read(skip * bs, bs * count)
        self.files[words["of"]] = data
        return f"{count}+0 records in\n{count}+0 records out\n"

    def readFile(self, path):
        return self.files[path]

    def readMemory(self, addr, size):
        return self.mem.read_phys(addr, size)

    def writeMemory(self, addr, data):
        self.mem.write_phys(addr, data)


def test_camera_memory_reads_whole_pages_once_and_slices_them():
    cam = FakeCamera(camera_image())
    mem = mprdump.CameraMemory(cam.run, cam, pid=148)
    data = mem.read(BLOCKS, 16 * 60)  # spans two pages
    assert data[:8] == struct.pack("<2I", *expected_blocks()[0])
    assert cam.commands == [mprdump.dd_cmd(148, "mem", PAGE, BLOCKS // PAGE, 2, "mem")]
    mem.read(BLOCKS + 8, 8)
    assert len(cam.commands) == 1          # cached
    mem.read(BLOCKS + 8, 8, fresh=True)
    assert len(cam.commands) == 2          # fresh reads go back to the camera


def test_camera_memory_rejects_a_short_or_failed_dump():
    cam = FakeCamera(camera_image())
    cam_run = cam.run
    cam.run = lambda cmd: (cam_run(cmd), "dd: /proc/148/mem: Input/output error\n0+0 records out\n")[1]
    with pytest.raises(mprdump.MprDumpError, match="dd"):
        mprdump.CameraMemory(cam.run, cam, pid=148).read(BLOCKS, 8)


def test_camera_memory_resolves_frames_and_round_trips_a_write():
    image = camera_image()
    cam = FakeCamera(image)
    mem = mprdump.CameraMemory(cam.run, cam, pid=148)
    assert mem.phys_page(BLOCKS + 16) == image.phys_page(BLOCKS + 16)
    writes = mprdump.plan_writes(mprdump.resolve(mem, MPRCTRL_BASE, LIBMPR_BASE), with_1_1(), [("L", "FINE")])
    mprdump.apply_writes(mem, writes, log=lambda _: None)
    assert image.read(BLOCKS + 16, 8) == writes[0].new


# --- whole session against the fake camera ---

MAPS = (f"{MPRCTRL_BASE:08x}-{MPRCTRL_BASE + 0x31000:08x} r-xp 00000000 fc:8f 32606      /usr/lib/libmprctrl.so\n"
        f"{MPRCTRL_BASE + 0x39000:08x}-{MPRCTRL_BASE + 0x3d000:08x} rw-p 00031000 fc:8f 32606      /usr/lib/libmprctrl.so\n"
        f"{LIBMPR_BASE:08x}-{LIBMPR_BASE + 0x7af000:08x} r-xp 00000000 fc:8f 16357      /usr/lib/libmpr.so\n")
CODE_PAGE = bytes(range(256)) * 16


class FakeShellCamera(FakeCamera):
    def __init__(self, mem):
        super().__init__(mem)
        self.pid, self.uptime = 148, 100.0
        mem.poke(MPRCTRL_BASE + 0x16000, CODE_PAGE)

    def run(self, cmd):
        assert mprdump.is_allowed(cmd), cmd
        if cmd.startswith("dd "):
            return super().run(cmd)
        self.commands.append(cmd)
        if cmd == "pidof im.elf":
            return f"{self.pid}\n"
        if cmd == "cat /proc/uptime":
            self.uptime += 1
            return f"{self.uptime:.2f} 50.00\n"
        return MAPS if cmd.endswith("/maps") else ""


BUILD_PAGES = [("libmprctrl.so", 0x16000, CODE_PAGE)]


def session(cam, **kw):
    return mprdump.run_session(cam.run, cam, with_1_1(), BUILD_PAGES, log=lambda _: None, **kw)


def test_read_only_session_reports_the_state_and_writes_nothing():
    image = camera_image()
    cam = FakeShellCamera(image)
    report = session(cam)
    assert report["state_1_1"] == "zero"
    assert report["stock_mismatches"] == []
    assert report["rows"][1]["vaddr"] == BLOCKS + 16
    assert report["size_rows_3_2"]["L"] == (7360, 4912, 7360 * 4912)
    assert "writes" not in report and image.phys_writes == []


def test_fill_session_writes_the_block_and_reports_the_new_state():
    image = camera_image()
    report = session(FakeShellCamera(image), targets=[("L", "FINE")])
    assert [w["action"] for w in report["writes"]] == ["written"]
    assert report["after"]["state_1_1"] == "mixed"
    assert image.read(BLOCKS + 16, 8) == struct.pack("<2I", *with_1_1()[1])


def test_session_refuses_a_camera_that_runs_other_code():
    image = camera_image()
    cam = FakeShellCamera(image)
    image.poke(MPRCTRL_BASE + 0x16000 + 0x148, b"\xff")
    with pytest.raises(mprdump.MprDumpError, match="not this firmware build"):
        session(cam, targets=[("L", "FINE")])
    assert image.phys_writes == []


def test_session_reports_a_restart():
    cam = FakeShellCamera(camera_image())
    pidof = iter(["148\n", "211\n"])
    run = cam.run
    cam.run = lambda cmd: next(pidof) if cmd == "pidof im.elf" else run(cmd)
    with pytest.raises(mprdump.MprDumpError, match="restarted"):
        session(cam)
