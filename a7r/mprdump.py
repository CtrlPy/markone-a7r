"""Stage 3: read the shot-counter estimates in the running camera; optionally fill the 1:1 ones.

The remaining-shots count uses per-shot JPEG estimates that the camera computes
once at start-up and keeps in the heap of its main process (see a7r.mprtable and
docs/findings/aspect-ratio.md section 10). This tool follows the pointer chain
in the running im.elf and compares the 60 full-frame JPEG blocks with what the
start-up code would compute from the camera's current Backup.bin.

Default (read-only): nothing in the camera is changed. Memory is read with the
camera's own busybox dd from /proc/<pid>/mem into the RAM-only /android/a7r and
fetched from there. Before anything is interpreted, one code page of
libmprctrl.so and of libmpr.so in the camera is compared with the local 3.20
files, and every pointer and count on the way is checked.

--fill SIZE:QUALITY (1:1 only, e.g. L:FINE) writes the formula value into that
block, 8 bytes, through Sony's service-mode memory command at the physical
address. It refuses unless the formula reproduces all 18 stock 3:2 and 16:9
blocks, the frame is identical to the process view of the page, and the block
holds zeros. Each write is read back through both views. --undo writes the
zeros back. RAM only: a battery pull restores the start-up state.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.mprdump fw/Sony-PMCA-RE dumps/<name> --lib-dir fw/out/.../lib
"""
import argparse
import json
import re
import struct
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from a7r import mprtable as m
from a7r.mempatch import PROCESS, WORK, find_text_base
from a7r.physmem import PAGE, FrameMismatch, PhysMemError, check_live_page_before_write, parse_pagemap

FILL_ASPECT = "1:1"
FILL_SIZES = ("L", "M", "S")
STOCK_ASPECTS = ("3:2", "16:9")
MAX_ESTIMATE = 64 << 20  # bytes; the largest stock estimate (3:2 L EXFINE max) is about 38 MiB
BLOCK = 8                # {u32 target, u32 max}
RESTART_TOLERANCE = 15.0  # seconds the uptime may lag behind the wall clock between two sessions

ALLOWED = [re.compile(p) for p in (
    r"uname -a",
    rf"pidof {re.escape(PROCESS)}",
    r"cat /proc/\d+/maps",
    r"cat /proc/uptime",
    rf"mkdir -p {WORK}",
    rf"dd if=/proc/\d+/(mem|pagemap) of={WORK}/(mem|pm)\.bin bs=\d+ skip=\d+ count=\d+",
)]


class MprDumpError(Exception):
    pass


def is_allowed(cmd):
    return any(p.fullmatch(cmd) for p in ALLOWED)


def dd_cmd(pid, source, bs, skip, count, name):
    return f"dd if=/proc/{pid}/{source} of={WORK}/{name}.bin bs={bs} skip={skip} count={count}"


# --- pointer chain ---

@dataclass
class Snapshot:
    still_mgr: int
    size_table_addr: int
    size_rows: list
    block_addrs: list
    blocks: list


def _u32s(data):
    return struct.unpack(f"<{len(data) // 4}I", data)


def resolve(mem, mprctrl_base, libmpr_base):
    """Follow MprCtrl::mp_stillMgr to the 60 full-frame JPEG estimate blocks, checking every step."""
    (still_mgr,) = _u32s(mem.read(mprctrl_base + m.MPRCTRL_MP_STILLMGR, 4))
    if not still_mgr:
        raise MprDumpError("MprCtrl::mp_stillMgr is null")
    _vtable, size_table, ssi, count = _u32s(mem.read(still_mgr, 16))
    want_ssi = mprctrl_base + m.MPRCTRL_SSI_TABLE
    if (ssi, count) != (want_ssi, m.MPRCTRL_SSI_COUNT):
        raise MprDumpError(f"StillSizeInfo is {ssi:#x} x {count}, expected {want_ssi:#x} x {m.MPRCTRL_SSI_COUNT}")
    (mpr_ptr,) = _u32s(mem.read(libmpr_base + m.LIBMPR_SSI_PTR, 4))
    (mpr_num,) = _u32s(mem.read(libmpr_base + m.LIBMPR_SSI_NUM, 4))
    if (mpr_ptr, mpr_num) != (ssi, count):
        raise MprDumpError(f"libmpr holds {mpr_ptr:#x} x {mpr_num}, not the table of libmprctrl")
    record = m.StillSizeInfo.unpack(mem.read(ssi, m.StillSizeInfo.SIZE))
    want = m.StillSizeInfo(0, 1, mprctrl_base + m.MPRCTRL_JPEG_FF_TABLE, 60, 10)
    if record != want:
        raise MprDumpError(f"StillSizeInfo record 0 is {record}, expected {want}")
    entries = _u32s(mem.read(record.table, 60 * 8))
    addrs = []
    for i in range(60):
        n, ptr = entries[2 * i], entries[2 * i + 1]
        if n != 1 or not ptr or ptr % 4:
            raise MprDumpError(f"table entry {i} is {{{n}, {ptr:#x}}}, expected {{1, block}}")
        addrs.append(ptr)
    if len(set(addrs)) != 60:
        raise MprDumpError("table entries share a block")
    blocks = [_u32s(mem.read(a, BLOCK)) for a in addrs]
    raw = mem.read(size_table, m.STILL_SIZE_TABLE_BYTES)
    size_rows = [struct.unpack_from("<HHI", raw, 8 * i) for i in range(len(raw) // 8)]
    return Snapshot(still_mgr, size_table, size_rows, addrs, blocks)


# --- comparison with the formula ---

@dataclass(frozen=True)
class Row:
    index: int
    size: str
    aspect: str
    quality: str
    ram: tuple
    expected: tuple


def rows(blocks, expected):
    return [Row(i, m.SIZES[i // 15], m.TABLE_ASPECTS[i % 15 // 3], m.QUALITIES[i % 3],
                tuple(blocks[i]), tuple(expected[i])) for i in range(60)]


def stock_mismatches(table):
    """Stock 3:2 and 16:9 modes (L, M, S) whose RAM block is not what the formula gives."""
    return [r for r in table if r.aspect in STOCK_ASPECTS and r.size in FILL_SIZES and r.ram != r.expected]


def hidden_state(table, aspect):
    """'zero', 'filled', 'mixed' (some of each) or 'unexpected' for the L/M/S blocks of an aspect."""
    part = [r for r in table if r.aspect == aspect and r.size in FILL_SIZES]
    if all(r.ram == (0, 0) for r in part):
        return "zero"
    if all(r.ram == r.expected for r in part):
        return "filled"
    if all(r.ram in ((0, 0), r.expected) for r in part):
        return "mixed"
    return "unexpected"


# --- writes ---

@dataclass(frozen=True)
class Write:
    index: int
    vaddr: int
    old: bytes
    new: bytes


def parse_target(text):
    size, _, quality = text.partition(":")
    if size not in FILL_SIZES or quality not in m.QUALITIES:
        raise ValueError(f"target must be SIZE:QUALITY with SIZE in {FILL_SIZES} and QUALITY in {m.QUALITIES}: {text!r}")
    return size, quality


def plan_writes(snap, expected, targets, undo=False):
    """Writes that put the formula value into the given 1:1 blocks (or zeros back with undo)."""
    table = rows(snap.blocks, expected)
    bad = stock_mismatches(table)
    if bad:
        names = ", ".join(f"{r.aspect} {r.size} {r.quality}" for r in bad[:4])
        raise MprDumpError(f"the formula does not reproduce {len(bad)} stock block(s) ({names}); not writing")
    if len(set(targets)) != len(targets):
        raise MprDumpError("a target is listed twice")
    writes = []
    for size, quality in targets:
        index = m.jpeg_index(size, FILL_ASPECT, quality)
        target, maximum = expected[index]
        if not target and not maximum:
            raise MprDumpError(f"Backup.bin has no {FILL_ASPECT} estimate for {size} {quality}")
        if not 0 < target <= maximum <= MAX_ESTIMATE:
            raise MprDumpError(f"implausible estimate for {size} {quality}: target {target}, max {maximum}")
        vaddr = snap.block_addrs[index]
        if vaddr % PAGE + BLOCK > PAGE:
            raise MprDumpError(f"block {index} at {vaddr:#x} crosses a page")
        value, zeros = struct.pack("<2I", target, maximum), bytes(BLOCK)
        writes.append(Write(index, vaddr, value, zeros) if undo else Write(index, vaddr, zeros, value))
    return writes


def apply_writes(mem, writes, log=print, attempts=3):
    """Apply each write through the physical frame; stop at the first problem."""
    results = []
    for w in writes:
        page, off = w.vaddr - w.vaddr % PAGE, w.vaddr % PAGE
        for attempt in range(attempts):
            frame = mem.phys_page(w.vaddr)
            try:
                decision = check_live_page_before_write(
                    mem.read_phys(frame, PAGE), mem.read(page, PAGE, fresh=True), off, w.old, w.new)
                break
            except FrameMismatch as e:  # a live page can change between the two reads: look again
                if attempt == attempts - 1:
                    raise MprDumpError(f"block {w.index} at {w.vaddr:#x}: {e}") from e
            except PhysMemError as e:
                raise MprDumpError(f"block {w.index} at {w.vaddr:#x}: {e}") from e
        if decision == "write":
            mem.write_phys(frame + off, w.new)
            log(f"block {w.index}: wrote {w.new.hex()} at physical {frame + off:#x} (virtual {w.vaddr:#x})")
        else:
            log(f"block {w.index}: already {w.new.hex()}, nothing written")
        back_phys = mem.read_phys(frame + off, len(w.new))
        back_proc = mem.read(w.vaddr, len(w.new), fresh=True)
        if back_phys != w.new or back_proc != w.new:
            raise MprDumpError(f"block {w.index}: read-back mismatch, physical {back_phys.hex()}, "
                               f"process {back_proc.hex()}, wanted {w.new.hex()}")
        results.append({"index": w.index, "vaddr": w.vaddr, "physical": frame + off,
                        "old": w.old.hex(), "new": w.new.hex(),
                        "action": "written" if decision == "write" else "already"})
    return results


# --- camera access ---

class CameraMemory:
    """Memory of one camera process: reads through busybox dd, frames through MemoryDump.

    run is a function that executes one allow-listed shell command and returns its output;
    camera needs readFile, readMemory and writeMemory (Sony-PMCA-RE service device).
    """

    def __init__(self, run, camera, pid):
        self.run, self.camera, self.pid = run, camera, pid
        self.cache = {}

    def _dump(self, source, bs, skip, count, name):
        out = self.run(dd_cmd(self.pid, source, bs, skip, count, name))
        data = self.camera.readFile(f"{WORK}/{name}.bin") or b""
        if f"{count}+0 records out" not in out or len(data) != bs * count:
            raise MprDumpError(f"dd of {source} at block {skip} failed: {out.strip()!r}, {len(data)} bytes")
        return data

    def read(self, vaddr, size, fresh=False):
        first, last = vaddr // PAGE, (vaddr + size - 1) // PAGE
        if fresh or any(p not in self.cache for p in range(first, last + 1)):
            data = self._dump("mem", PAGE, first, last - first + 1, "mem")
            for i, p in enumerate(range(first, last + 1)):
                self.cache[p] = data[i * PAGE:(i + 1) * PAGE]
        joined = b"".join(self.cache[p] for p in range(first, last + 1))
        return joined[vaddr % PAGE: vaddr % PAGE + size]

    def phys_page(self, vaddr):
        try:
            return parse_pagemap(self._dump("pagemap", 8, vaddr // PAGE, 1, "pm")) * PAGE
        except PhysMemError as e:
            raise MprDumpError(f"no frame for {vaddr:#x}: {e}") from e

    def read_phys(self, paddr, size):
        return bytes(self.camera.readMemory(paddr, size) or b"")

    def write_phys(self, paddr, data):
        self.camera.writeMemory(paddr, data)


def _one_pid(out):
    pids = re.findall(r"^\s*(\d+)\s*$", out, re.M)
    if len(pids) != 1:
        raise MprDumpError(f"expected one {PROCESS} pid, got {pids}")
    return int(pids[0])


def _uptime(out):
    m_ = re.search(r"^\s*(\d+\.\d+)\s", out, re.M)
    if not m_:
        raise MprDumpError(f"cannot read /proc/uptime: {out.strip()!r}")
    return float(m_.group(1))


def restarted_since(previous, wall, uptime, tolerance=RESTART_TOLERANCE):
    """True when the camera's uptime has not kept pace with the wall clock since the previous session.

    previous is {"wall": seconds, "uptime": seconds} from the last session, or None. A restart
    resumes from the boot snapshot and silently drops every RAM change, so it must not go unnoticed.
    (A camera that was switched off in between looks the same: its uptime stands still.)
    """
    if not previous:
        return False
    return uptime + tolerance < previous["uptime"] + (wall - previous["wall"])


def _summary(snap, expected):
    table = rows(snap.blocks, expected)
    return {
        "stock_mismatches": [asdict(r) for r in stock_mismatches(table)],
        "state_1_1": hidden_state(table, FILL_ASPECT),
        "rows": [asdict(r) | {"vaddr": snap.block_addrs[r.index]} for r in table],
        "size_rows_1_1": {s: snap.size_rows[i * 5] for i, s in enumerate(FILL_SIZES)},
        "size_rows_3_2": {s: snap.size_rows[i * 5 + 3] for i, s in enumerate(FILL_SIZES)},
    }


def run_session(run, camera, expected, build_pages, targets=(), undo=False, log=print,
                previous=None, clock=time.time, checkpoint=lambda wall, uptime: None):
    """Dump and check the estimates of the running camera; apply the planned writes if any.

    build_pages: (library, ELF vaddr, 4096 bytes of the local 3.20 file) code pages that the
    camera must hold unchanged before anything else is trusted.
    previous / clock / checkpoint: uptime bookkeeping across sessions (see restarted_since);
    checkpoint(wall, uptime) is called at the start and at the end of the session.
    """
    pid = _one_pid(run(f"pidof {PROCESS}"))
    uptime = _uptime(run("cat /proc/uptime"))
    wall = clock()
    restarted = restarted_since(previous, wall, uptime)
    checkpoint(wall, uptime)
    if restarted:
        log(f"RESTART: uptime is {uptime:.0f} s but the previous session ended at {previous['uptime']:.0f} s, "
            f"{wall - previous['wall']:.0f} s ago. RAM changes made before that are gone.")
        if targets:
            raise MprDumpError("the camera restarted since the previous session; nothing written. "
                               "Run again once that is understood.")
    maps = run(f"cat /proc/{pid}/maps")
    try:
        bases = {lib: find_text_base(maps, lib) for lib in ("libmprctrl.so", "libmpr.so")}
    except Exception as e:
        raise MprDumpError(str(e)) from e
    run(f"mkdir -p {WORK}")
    mem = CameraMemory(run, camera, pid)
    for lib, vaddr, page in build_pages:
        if mem.read(bases[lib] + vaddr, PAGE) != page:
            raise MprDumpError(f"{lib} page {vaddr:#x} in the camera differs from the local file: not this firmware build")
    snap = resolve(mem, bases["libmprctrl.so"], bases["libmpr.so"])
    report = {"pid": pid, "uptime": uptime, "wall": wall, "restart_since_previous": restarted,
              "bases": bases, "still_mgr": snap.still_mgr,
              "size_table": snap.size_table_addr, "maps": maps, **_summary(snap, expected)}
    log(f"{PROCESS} pid {pid}, libmprctrl {bases['libmprctrl.so']:#x}, libmpr {bases['libmpr.so']:#x}, "
        f"stillMgr {snap.still_mgr:#x}")
    log(f"stock blocks differing from the formula: {len(report['stock_mismatches'])} of 18")
    log(f"{FILL_ASPECT} blocks: {report['state_1_1']}")
    if targets:
        report["writes"] = apply_writes(mem, plan_writes(snap, expected, targets, undo), log)
        mem.cache.clear()
        after = _summary(resolve(mem, bases["libmprctrl.so"], bases["libmpr.so"]), expected)
        report["after"] = {k: after[k] for k in ("stock_mismatches", "state_1_1", "rows")}
        log(f"after: {FILL_ASPECT} blocks {after['state_1_1']}, stock mismatches {len(after['stock_mismatches'])}")
    pid_end, uptime_end = _one_pid(run(f"pidof {PROCESS}")), _uptime(run("cat /proc/uptime"))
    report["uptime_end"] = uptime_end
    checkpoint(clock(), uptime_end)
    if pid_end != pid or uptime_end < uptime:
        raise MprDumpError(f"the camera restarted during the session (pid {pid} -> {pid_end}, "
                           f"uptime {uptime} -> {uptime_end})")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.mprdump", description=__doc__.splitlines()[0])
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--lib-dir", type=Path, required=True, help="lib/ of the locally unpacked 3.20 firmware")
    ap.add_argument("--backup", type=Path, help="use this Backup.bin instead of reading the camera's (read-only runs)")
    ap.add_argument("--fill", action="append", default=[], type=parse_target, metavar="SIZE:QUALITY",
                    help=f"fill this {FILL_ASPECT} block with the formula value (RAM only), e.g. L:FINE")
    ap.add_argument("--undo", action="store_true", help="with --fill: write zeros back instead")
    ap.add_argument("--model", default="ILCE-7R")
    ap.add_argument("--state", type=Path, default=Path("work/camera-session.json"),
                    help="where the uptime of the last session is kept, to notice a restart in between")
    args = ap.parse_args(argv)
    if args.undo and not args.fill:
        ap.error("--undo needs --fill")
    if args.fill and args.backup:
        ap.error("--fill computes values from the camera's current Backup.bin; do not pass --backup")

    from a7r.backup import BackupFile
    from a7r.stage0 import check_backup
    from a7r.stage3 import TerminalSession

    ctrl, mpr = m.Elf(args.lib_dir / "libmprctrl.so"), m.Elf(args.lib_dir / "libmpr.so")
    if ctrl.symbol("_ZN7MprCtrl11mp_stillMgrE") != m.MPRCTRL_MP_STILLMGR:
        raise SystemExit("local libmprctrl.so is not the expected 3.20 build")
    build_pages = [(e.path.name, v, e.raw[e.offset(v): e.offset(v) + PAGE])
                   for e, v in ((ctrl, 0x16000), (mpr, 0x523000))]

    sys.path.insert(0, str(args.pmca_root))
    from pmca.commands.usb import senserShellCommand

    args.outdir.mkdir(parents=True, exist_ok=False)
    done = {}
    previous = json.loads(args.state.read_text()) if args.state.is_file() else None

    def checkpoint(wall, uptime):
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps({"wall": wall, "uptime": uptime}))

    def log(msg):
        print(msg, flush=True)
        with open(args.outdir / "transcript.txt", "a") as f:  # line by line: survives a dropped USB link
            f.write(msg + "\n")

    def complete(camera):
        camera.readHasp()
        if args.backup:
            image = args.backup.read_bytes()
        else:
            image = camera.getBackupPresetData(True)
            (args.outdir / "Backup.bin").write_bytes(image)
        check_backup(image, args.model)
        props = {pid: p.data for pid, p in BackupFile(image).properties.items()}
        expected = m.expected_jpeg_estimates(props, ctrl)
        camera.setTerminalEnable(False)
        camera.setTerminalEnable(True)
        try:
            session = TerminalSession(camera.dev, max_polls=6000, poll_delay=0.01)

            def run(cmd):
                if not is_allowed(cmd):
                    raise MprDumpError(f"command not allowed: {cmd}")
                log(f"$ {cmd}")
                out = session.run(cmd)
                if not cmd.endswith("/maps"):
                    log(out.rstrip())
                return out

            run("uname -a")  # flush the banner
            report = run_session(run, camera, expected, build_pages, args.fill, args.undo, log,
                                 previous=previous, checkpoint=checkpoint)
            (args.outdir / "maps.txt").write_text(report.pop("maps"))
            (args.outdir / "report.json").write_text(json.dumps(report, indent=1))
            done.update(report)
        finally:
            camera.setTerminalEnable(False)

    senserShellCommand(complete=complete)
    if not done:
        raise SystemExit("session did not complete; see the output above")
    for r in done.get("after", done)["rows"]:
        if r["aspect"] in STOCK_ASPECTS + (FILL_ASPECT,) and r["size"] in FILL_SIZES:
            mark = "ok" if r["ram"] == r["expected"] else "DIFF"
            print(f"{r['aspect']:>4} {r['size']} {r['quality']:<6} ram {r['ram']}  formula {r['expected']}  {mark}")
    return 1 if done["stock_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
