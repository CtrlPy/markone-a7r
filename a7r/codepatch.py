"""Stage 3 without the service terminal: apply a verified byte patch to code in RAM.

The code of a camera library sits in page-cache frames whose content is the
library file itself. The patch is written through Sony's MemoryDump at a
physical address, but only into a frame whose whole 4096 bytes equal the page
of the local 3.20 file, except the patch site, which must hold the original
bytes (or already the replacement). A frame that differs anywhere else is not
the library page and is never written. No shell or terminal is used: the
terminal crashes this camera's kernel too often (docs/LOG.md, 2026-11-10).

Which frame holds the page is not known without the terminal, so the frames
seen on the camera before are tried in turn (--phys adds more). RAM only: a
battery pull restores the stock code. The session stays in service mode for
at least 3 s, and a7r.usbwatch tells afterwards whether the camera restarted.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.codepatch fw/Sony-PMCA-RE work/<name> --lib fw/out/.../lib/libObj.so
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from a7r.mempatch import MemPatchError, find_text_base
from a7r.mprphys import RAM_AREAS, check_address, dwell
from a7r.physmem import PAGE, PhysMemError, check_page_before_write, parse_pagemap

PROCESS_PID = 148  # im.elf in every boot seen (the boot snapshot keeps it)

# frames that held the libObj.so page of the Image Size patch: 2026-11-10 (13:00), 2026-11-09
CANDIDATE_FRAMES = {"libObj.so": [0x88BB7000, 0x88CC2000]}


class CodePatchError(Exception):
    pass


def frame_from_proc(camera, pid, lib, offset):
    """Physical frame of `lib` + `offset` in process `pid`, from /proc read with Sony's file command."""
    cmdline = bytes(camera.readFile(f"/proc/{pid}/cmdline") or b"")
    if b"im.elf" not in cmdline:
        raise CodePatchError(f"pid {pid} is not im.elf (cmdline {cmdline[:40]!r})")
    maps = bytes(camera.readFile(f"/proc/{pid}/maps") or b"").decode("latin1")
    if not maps.strip():
        raise CodePatchError(f"reading /proc/{pid}/maps gave nothing")
    try:
        base = find_text_base(maps, lib)
    except MemPatchError as e:
        raise CodePatchError(str(e)) from e
    index = (base + offset) // PAGE
    pagemap = bytes(camera.readFile(f"/proc/{pid}/pagemap") or b"")
    entry = pagemap[8 * index: 8 * index + 8]
    if len(entry) != 8:
        raise CodePatchError(f"/proc/{pid}/pagemap gave {len(pagemap)} bytes, entry {index} is beyond it")
    try:
        return parse_pagemap(entry) * PAGE
    except PhysMemError as e:
        raise CodePatchError(f"{lib} page at {base + offset - offset % PAGE:#x}: {e}") from e


def scan_areas(near=()):
    """All ordinary Linux RAM, starting a little below the first frame seen before."""
    if not near:
        return list(RAM_AREAS)
    first, rest = [], []
    for lo, hi in RAM_AREAS:
        if lo <= near[0] < hi:
            split = max(lo, (near[0] & ~0xFFFFF) - 0x800000)
            first.append((split, hi))
            if split > lo:
                rest.append((lo, split))
        else:
            rest.append((lo, hi))
    return first + rest


def scan_for_page(camera, file_page, site, old, new, areas, chunk=0x100000, budget=60.0,
                  clock=time.monotonic, log=print):
    """First frame in `areas` whose page equals `file_page` apart from the site, or None.

    Reads RAM in chunks through MemoryDump; stops when `budget` seconds have passed.
    """
    for lo, hi in areas:
        check_address(lo, hi - lo)
    start, done = clock(), 0
    head = file_page[:min(site, 256)]
    for lo, hi in areas:
        addr = lo
        while addr < hi:
            if clock() - start > budget:
                log(f"scan: time budget used up after {done >> 20} MiB")
                return None
            size = min(chunk, hi - addr)
            data = bytes(camera.readMemory(addr, size) or b"")
            if len(data) != size:
                raise CodePatchError(f"MemoryDump at {addr:#x} gave {len(data)} of {size} bytes")
            for i in range(0, size, PAGE):
                page = data[i:i + PAGE]
                if head and page[:len(head)] != head:
                    continue
                try:
                    check_page_before_write(page, file_page, site, old, new)
                except PhysMemError:
                    continue
                log(f"scan: page found at {addr + i:#x} after {(done + i) >> 20} MiB")
                return addr + i
            addr += size
            done += size
    log(f"scan: page not found in {done >> 20} MiB")
    return None


def find_frame(camera, file_page, site, old, new, candidates):
    for frame in candidates:
        check_address(frame)
        page = bytes(camera.readMemory(frame, PAGE) or b"")
        try:
            return frame, check_page_before_write(page, file_page, site, old, new)
        except PhysMemError:
            continue
    raise CodePatchError("no candidate frame holds the library page; nothing written")


def apply(camera, patch, lib, candidates, log=print):
    if hashlib.sha256(lib).hexdigest() != patch.sha256:
        raise CodePatchError(f"local {patch.file} sha256 differs from the build the patch was made for")
    results = []
    for off, old, new in patch.edits:
        base, site = off - off % PAGE, off % PAGE
        if site + len(new) > PAGE:
            raise CodePatchError(f"edit at {off:#x} crosses a page")
        file_page = lib[base: base + PAGE]
        frame, decision = find_frame(camera, file_page, site, old, new, candidates)
        if decision == "write":
            camera.writeMemory(frame + site, new)
            log(f"{patch.file} {off:#x}: wrote {new.hex()} at {frame + site:#x}")
        else:
            log(f"{patch.file} {off:#x}: already {new.hex()} at {frame + site:#x}")
        back = bytes(camera.readMemory(frame + site, len(new)) or b"")
        if back != new:
            raise CodePatchError(f"{patch.file} {off:#x}: read-back {back.hex()}, wanted {new.hex()}")
        results.append({"offset": off, "frame": frame, "physical": frame + site, "new": new.hex(),
                        "action": "written" if decision == "write" else "already"})
    return results


def main(argv=None):
    from a7r.patches import PATCHES

    ap = argparse.ArgumentParser(prog="a7r.codepatch", description=__doc__.splitlines()[0])
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--lib", type=Path, required=True, help="local libObj.so (3.20)")
    ap.add_argument("--patch", default="libobj-image-size-aspect-fallback",
                    choices=sorted(n for n, p in PATCHES.items() if p.file == "libObj.so"))
    ap.add_argument("--phys", action="append", default=[], type=lambda s: int(s, 0),
                    help="extra candidate frame (physical address), tried first")
    ap.add_argument("--scan", action="store_true",
                    help="if no candidate matches, search ordinary Linux RAM for the page (read-only) and patch it there")
    ap.add_argument("--scan-budget", type=float, default=60.0, help="seconds of searching at most (default 60)")
    ap.add_argument("--from-proc", action="store_true",
                    help="look the frame up in /proc/<im.elf>/pagemap, read with Sony's file command, and try it first")
    args = ap.parse_args(argv)
    patch = PATCHES[args.patch]
    lib = args.lib.read_bytes()
    candidates = args.phys + CANDIDATE_FRAMES[patch.file]
    for c in candidates:
        check_address(c)

    from a7r.usbwatch import journal_since, service_sessions
    sys.path.insert(0, str(args.pmca_root))
    from pmca.commands.usb import senserShellCommand

    args.outdir.mkdir(parents=True, exist_ok=False)
    report = {"patch": patch.name, "candidates": [hex(c) for c in candidates]}

    def log(msg):
        print(msg, flush=True)
        with open(args.outdir / "transcript.txt", "a") as f:
            f.write(msg + "\n")

    def complete(camera):  # no terminal is opened in this session
        start = time.monotonic()
        try:
            camera.readHasp()
            tried = list(candidates)
            if args.from_proc:
                off = patch.edits[0][0]
                try:
                    frame = frame_from_proc(camera, PROCESS_PID, patch.file, off)
                    report["proc_frame"] = hex(frame)
                    log(f"/proc: {patch.file} {off:#x} is in frame {frame:#x}")
                    check_address(frame)
                    tried = [frame] + [c for c in tried if c != frame]
                except CodePatchError as e:
                    report["proc_error"] = str(e)
                    log(f"/proc lookup failed: {e}")
            report["tried"] = [hex(c) for c in tried]
            try:
                report["results"] = apply(camera, patch, lib, tried, log)
            except CodePatchError as e:
                if not args.scan or "no candidate" not in str(e):
                    raise
                log(f"{e}; searching RAM")
                off, old, new = patch.edits[0]
                t0 = time.monotonic()
                frame = scan_for_page(camera, lib[off - off % PAGE: off - off % PAGE + PAGE], off % PAGE, old, new,
                                      scan_areas(CANDIDATE_FRAMES[patch.file]), budget=args.scan_budget, log=log)
                report["scan_seconds"] = round(time.monotonic() - t0, 1)
                if frame is None:
                    raise CodePatchError("the page was not found in RAM; nothing written")
                report["scan_frame"] = hex(frame)
                report["results"] = apply(camera, patch, lib, [frame], log)
        finally:
            dwell(start)

    since = time.strftime("%H:%M:%S", time.localtime(time.time() - 120))
    try:
        senserShellCommand(complete=complete)
    except CodePatchError as e:
        report["error"] = str(e)
        log(f"refused: {e}")
    finally:
        (args.outdir / "report.json").write_text(json.dumps(report, indent=1))
    sessions = []
    for _ in range(30):
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
    return 0 if "results" in report else 1


if __name__ == "__main__":
    sys.exit(main())
