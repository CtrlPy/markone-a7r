"""Stage 3 without the service terminal: check and fill the shot-counter estimates.

Closing Sony's service terminal on the running camera often crashes the kernel
(docs/LOG.md, 2026-11-10); service sessions that use only Sony's commands do
not. This tool uses only those: the Backup.bin read and MemoryDump at a
physical address. No shell, no terminal.

The 60 full-frame JPEG estimate blocks ({u32 target, u32 max}, see
a7r.mprtable) are 8-byte heap allocations of im.elf in one page. After a resume
from the boot snapshot the page is at the same place every time (virtual
0x0ac09000, physical 0x8a4b2000 on 2026-11-10), block i at page offset
0x138 + 16*i, each preceded by its glibc allocation header (0x15: size 16 in a
thread arena). Before the
page is trusted, all 60 blocks must agree with the formula applied to the
camera's current Backup.bin (the 1:1 L/M/S blocks may be zero or already
filled) and all 60 headers must be there. A wrong page cannot pass that.

Default: read-only. --fill SIZE:QUALITY writes the formula value into that 1:1
block (8 bytes, RAM only), after checking the whole page again, and reads it
back. --undo writes zeros back. A battery pull restores the start-up state.
After the session, a7r.usbwatch shows from the laptop's log whether the camera
restarted.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.mprphys fw/Sony-PMCA-RE dumps/<name> --lib-dir fw/out/.../lib
"""
import argparse
import json
import struct
import sys
import time
from pathlib import Path

from a7r import mprtable as m
from a7r.mprdump import FILL_ASPECT, FILL_SIZES, MAX_ESTIMATE, hidden_state, parse_target, rows
from a7r.physmem import PAGE

DEFAULT_PHYS_PAGE = 0x8A4B2000
FIRST_BLOCK = 0x138
HEADER = 0x15            # glibc chunk size 16 | NON_MAIN_ARENA (0x4) | PREV_INUSE (0x1): a thread arena (camera, 2026-11-10)
# Linux RAM without the reserved areas, from the kernel command line in the firmware
# (0800_appli/setting/kemco.txt): mem=256M@0x80000000, memrsv=0x28000@0x80000000,
# memrsv=0x13B1000@0x82D90000 (holds klog), memrsv=0x1980000@0x8E680000; the 576M at 0x9C000000
# is reserved as a whole. Anything else may be device space: never read or write it.
RAM_AREAS = [(0x80028000, 0x82D90000), (0x84141000, 0x8E680000)]
# Leaving service mode within ~0.66 s of entering it was followed by the camera staying away
# for 67-111 s (4 of 4); sessions of 0.69 s and more returned normally, stage1 sessions take 1.7-3.2 s.
MIN_SERVICE_SECONDS = 3.0


class MprPhysError(Exception):
    pass


def dwell(start, minimum=MIN_SERVICE_SECONDS, clock=time.monotonic, sleep=time.sleep):
    """Stay in service mode until at least `minimum` seconds have passed since `start`."""
    left = minimum - (clock() - start)
    if left > 0:
        sleep(left)


def check_address(paddr, size=PAGE):
    """Refuse anything but whole pages of ordinary Linux RAM."""
    if paddr % PAGE or size <= 0 or size % PAGE:
        raise MprPhysError(f"{paddr:#x} + {size:#x} is not page-aligned")
    if not any(lo <= paddr and paddr + size <= hi for lo, hi in RAM_AREAS):
        areas = ", ".join(f"{lo:#x}-{hi:#x}" for lo, hi in RAM_AREAS)
        raise MprPhysError(f"{paddr:#x} + {size:#x} is not inside ordinary Linux RAM ({areas})")


def block_offset(index):
    return FIRST_BLOCK + 16 * index


def page_blocks(page):
    return [struct.unpack_from("<2I", page, block_offset(i)) for i in range(60)]


def check_page(page, expected):
    """State of the 1:1 blocks ('zero', 'filled', 'mixed') if this is the estimate page, else raise."""
    if len(page) != PAGE:
        raise MprPhysError(f"expected 4096 bytes, got {len(page)}")
    stock = [i for i in range(60) if m.TABLE_ASPECTS[i % 15 // 3] in ("3:2", "16:9") and expected[i] != (0, 0)]
    if len(stock) < 18:
        raise MprPhysError("the Backup.bin values give fewer than 18 stock estimates; nothing to compare with")
    for i in range(60):
        (size,) = struct.unpack_from("<I", page, block_offset(i) - 4)
        if size != HEADER:
            raise MprPhysError(f"block {i}: allocation header {size:#x}, expected {HEADER:#x}")
    table = rows(page_blocks(page), expected)
    hidden = {r.index for r in table if r.aspect == FILL_ASPECT and r.size in FILL_SIZES}
    bad = [r for r in table if r.index not in hidden and r.ram != r.expected]
    if bad:
        names = ", ".join(f"{r.aspect} {r.size} {r.quality}" for r in bad[:4])
        raise MprPhysError(f"not the estimate page: {len(bad)} block(s) differ from the formula ({names})")
    state = hidden_state(table, FILL_ASPECT)
    if state == "unexpected":
        raise MprPhysError("1:1 blocks hold values that are neither zero nor the formula")
    return state


def fill(camera, phys, expected, targets, undo=False, log=print):
    check_address(phys)
    if len(set(targets)) != len(targets):
        raise MprPhysError("a target is listed twice")
    results = []
    for size, quality in targets:
        index = m.jpeg_index(size, FILL_ASPECT, quality)
        target, maximum = expected[index]
        if not target and not maximum:
            raise MprPhysError(f"Backup.bin has no {FILL_ASPECT} estimate for {size} {quality}")
        if not 0 < target <= maximum <= MAX_ESTIMATE:
            raise MprPhysError(f"implausible estimate for {size} {quality}: target {target}, max {maximum}")
        value, zeros = struct.pack("<2I", target, maximum), bytes(8)
        old, new = (value, zeros) if undo else (zeros, value)
        page = bytes(camera.readMemory(phys, PAGE) or b"")
        check_page(page, expected)  # the whole page, right before each write
        site = page[block_offset(index): block_offset(index) + 8]
        addr = phys + block_offset(index)
        if site == new:
            action = "already"
            log(f"block {index} ({size} {quality}): already {new.hex()}")
        elif site == old:
            camera.writeMemory(addr, new)
            action = "written"
            log(f"block {index} ({size} {quality}): wrote {new.hex()} at {addr:#x}")
        else:
            raise MprPhysError(f"block {index} holds {site.hex()}, expected {old.hex()}")
        back = bytes(camera.readMemory(addr, 8) or b"")
        if back != new:
            raise MprPhysError(f"block {index}: read-back {back.hex()}, wanted {new.hex()}")
        results.append({"index": index, "physical": addr, "old": old.hex(), "new": new.hex(), "action": action})
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.mprphys", description=__doc__.splitlines()[0])
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--lib-dir", type=Path, required=True, help="lib/ of the locally unpacked 3.20 firmware")
    ap.add_argument("--phys", type=lambda s: int(s, 0), default=DEFAULT_PHYS_PAGE,
                    help=f"physical address of the estimate page (default {DEFAULT_PHYS_PAGE:#x})")
    ap.add_argument("--fill", action="append", default=[], type=parse_target, metavar="SIZE:QUALITY")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--model", default="ILCE-7R")
    args = ap.parse_args(argv)
    if args.undo and not args.fill:
        ap.error("--undo needs --fill")
    check_address(args.phys)

    from a7r.backup import BackupFile
    from a7r.stage0 import check_backup
    from a7r.usbwatch import journal_since, service_sessions

    ctrl = m.Elf(args.lib_dir / "libmprctrl.so")
    sys.path.insert(0, str(args.pmca_root))
    from pmca.commands.usb import senserShellCommand

    args.outdir.mkdir(parents=True, exist_ok=False)
    report = {}

    def log(msg):
        print(msg, flush=True)
        with open(args.outdir / "transcript.txt", "a") as f:
            f.write(msg + "\n")

    def complete(camera):  # no terminal is opened in this session
        start = time.monotonic()
        try:
            work(camera)
        finally:
            dwell(start)

    def work(camera):
        camera.readHasp()
        image = camera.getBackupPresetData(True)
        (args.outdir / "Backup.bin").write_bytes(image)
        check_backup(image, args.model)
        props = {pid: p.data for pid, p in BackupFile(image).properties.items()}
        expected = m.expected_jpeg_estimates(props, ctrl)
        page = bytes(camera.readMemory(args.phys, PAGE) or b"")
        (args.outdir / "page.bin").write_bytes(page)
        report["aspect"] = props[0x01070012].hex()
        report["state_1_1"] = check_page(page, expected)
        log(f"estimate page at {args.phys:#x}: verified, 1:1 blocks {report['state_1_1']}, aspect {report['aspect']}")
        if args.fill:
            report["writes"] = fill(camera, args.phys, expected, args.fill, args.undo, log)
            after = bytes(camera.readMemory(args.phys, PAGE) or b"")
            report["state_1_1_after"] = check_page(after, expected)
            log(f"after: 1:1 blocks {report['state_1_1_after']}")

    # from a little before the start: the camera may already be in service mode (an earlier attempt switched it)
    since = time.strftime("%H:%M:%S", time.localtime(time.time() - 120))
    try:
        senserShellCommand(complete=complete)
    finally:
        (args.outdir / "report.json").write_text(json.dumps(report, indent=1))
    if "state_1_1" not in report:
        raise SystemExit("session did not complete; see the output above")
    for _ in range(30):  # watch the camera come back as USB storage
        time.sleep(1)
        sessions = service_sessions(journal_since(since))
        if sessions and sessions[-1].back_after is not None:
            break
    s = sessions[-1] if sessions else None
    verdict = "unknown" if not s or s.back_after is None else (
        f"RESTART (back after {s.back_after:.1f} s)" if s.restarted else f"no restart (back after {s.back_after:.1f} s)")
    report["after_session"] = verdict
    (args.outdir / "report.json").write_text(json.dumps(report, indent=1))
    log(f"after the session: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
