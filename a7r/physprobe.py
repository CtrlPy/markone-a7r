"""Stage 3 probe (read-only): which address space does senser MemoryDump use?

Reads the libObj.so code page that holds a patch site three ways and compares
each with the same page of the local libObj.so file:
  1. process view: busybox dd from /proc/<pid>/mem (known to work)
  2. senser MemoryDump at the physical address (pagemap PFN)
  3. senser MemoryDump at the kernel linear address of that frame
No foreign binaries are run and nothing is written except small files in the
RAM-only /android/a7r.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.physprobe fw/Sony-PMCA-RE work/physprobe-<date> --lib fw/out/.../libObj.so
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

from a7r.mempatch import PROCESS, WORK, find_text_base
from a7r.patches import LIBOBJ_IMAGE_SIZE_ASPECT_FALLBACK as PATCH
from a7r.physmem import PAGE, kernel_virt, pagemap_offset, parse_pagemap, ram_start
from a7r.stage3 import TerminalSession


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.physprobe")
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("logdir", type=Path)
    ap.add_argument("--lib", type=Path, required=True, help="local libObj.so (3.20)")
    args = ap.parse_args(argv)

    lib = args.lib.read_bytes()
    if hashlib.sha256(lib).hexdigest() != PATCH.sha256:
        raise SystemExit("local libObj.so is not the expected 3.20 build")
    off = PATCH.edits[0][0]
    file_page = lib[off - off % PAGE: off - off % PAGE + PAGE]

    sys.path.insert(0, str(args.pmca_root))
    from pmca.commands.usb import senserShellCommand

    args.logdir.mkdir(parents=True, exist_ok=False)
    result = {}

    def log(msg):
        print(msg, flush=True)
        with open(args.logdir / "transcript.txt", "a") as f:
            f.write(msg + "\n")

    def complete(camera):
        camera.readHasp()
        camera.setTerminalEnable(False)
        camera.setTerminalEnable(True)
        try:
            s = TerminalSession(camera.dev, max_polls=6000, poll_delay=0.01)
            s.run("uname -a")
            pid = int(re.findall(r"^\s*(\d+)\s*$", s.run(f"pidof {PROCESS}"), re.M)[0])
            base = find_text_base(s.run(f"cat /proc/{pid}/maps"), PATCH.file)
            vpage = base + off - off % PAGE
            log(f"pid {pid}, libObj base {base:#x}, page {vpage:#x}")
            s.run(f"mkdir -p {WORK}")
            for cmd in (f"dd if=/proc/{pid}/mem of={WORK}/page.bin bs={PAGE} skip={vpage // PAGE} count=1",
                        f"dd if=/proc/{pid}/pagemap of={WORK}/pm.bin bs=8 skip={pagemap_offset(vpage) // 8} count=1"):
                log(f"$ {cmd}")
                log(s.run(cmd).rstrip())
            proc_page = camera.readFile(f"{WORK}/page.bin")
            result["process_view_matches_file"] = proc_page == file_page
            log(f"process view == file page: {result['process_view_matches_file']}")
            pfn = parse_pagemap(camera.readFile(f"{WORK}/pm.bin"))
            ram = ram_start(s.run("cat /proc/iomem"))
            phys = pfn * PAGE
            kv = kernel_virt(phys, ram)
            log(f"pfn {pfn:#x} phys {phys:#x} ram start {ram:#x} kernel virt {kv:#x}")
            for label, addr in (("physical", phys), ("kernel_virtual", kv)):
                try:
                    data = camera.readMemory(addr, PAGE)
                    ok = data == file_page
                    log(f"MemoryDump {label} {addr:#x}: {len(data or b'')} bytes, matches file page: {ok}")
                    result[label] = ok
                except Exception as e:  # report and continue: this is a probe
                    log(f"MemoryDump {label} {addr:#x}: error {e}")
                    result[label] = f"error {e}"
        finally:
            camera.setTerminalEnable(False)

    senserShellCommand(complete=complete)
    log(f"result {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
