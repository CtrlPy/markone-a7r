"""Stage 3: patch the running camera process in RAM via /proc/<pid>/mem.

For each edit of a BytePatch (whose file is mapped by the main camera process
im.elf), compute the absolute address from /proc/<pid>/maps, read the current
bytes, check they are the expected originals, write the replacement with
busybox dd and read back. Nothing touches flash; a power cycle undoes it.
If memory already holds the replacement the edit is skipped.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.mempatch fw/Sony-PMCA-RE libobj-image-size-aspect-fallback work/mempatch-<date>
"""
import argparse
import re
import sys
from pathlib import Path

from a7r.stage3 import TerminalSession

WORK = "/android/a7r"
PROCESS = "im.elf"


class MemPatchError(Exception):
    pass


def find_text_base(maps, lib):
    for line in maps.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[5].endswith("/" + lib) and parts[1].startswith("r-x") and int(parts[2], 16) == 0:
            return int(parts[0].split("-")[0], 16)
    raise MemPatchError(f"{lib} not mapped as r-x at offset 0")


def mempatch_steps(patch, pid, base):
    steps = [("run", f"mkdir -p {WORK}")]
    for off, old, new in patch.edits:
        addr = base + off
        n = len(old)
        steps += [
            ("read", f"dd if=/proc/{pid}/mem of={WORK}/mem_before.bin bs=1 skip={addr} count={n}", f"{WORK}/mem_before.bin", old, new),
            ("stage", f"{WORK}/mem_patch.bin", new),
            ("write", f"dd if={WORK}/mem_patch.bin of=/proc/{pid}/mem bs=1 seek={addr} count={n} conv=notrunc"),
            ("verify", f"dd if=/proc/{pid}/mem of={WORK}/mem_after.bin bs=1 skip={addr} count={n}", f"{WORK}/mem_after.bin", new),
        ]
    return steps


def run_mempatch(steps, session, camera, log=print):
    allowed = {s[1] for s in steps if s[0] in ("run", "read", "write", "verify")}
    skip_write = False

    def run(cmd):
        if cmd not in allowed:
            raise MemPatchError(f"command not allowed: {cmd}")
        log(f"$ {cmd}")
        out = session.run(cmd)
        log(out.rstrip())
        return out

    for step in steps:
        kind = step[0]
        if kind == "run":
            run(step[1])
        elif kind == "read":
            run(step[1])
            got = camera.readFile(step[2])
            old, new = step[3], step[4]
            if got == new:
                log(f"already patched ({got.hex()}), skipping write")
                skip_write = True
            elif got != old:
                raise MemPatchError(f"memory holds {got.hex() if got else got}, expected {old.hex()}; not writing")
            else:
                skip_write = False
                log(f"ok: original bytes {got.hex()}")
        elif kind == "stage":
            if not skip_write:
                camera.writeFile(step[1], step[2])
                if camera.readFile(step[1]) != step[2]:
                    raise MemPatchError("staged patch bytes did not read back")
        elif kind == "write":
            if not skip_write:
                run(step[1])
        elif kind == "verify":
            run(step[1])
            got = camera.readFile(step[2])
            if got != step[3]:
                raise MemPatchError(f"after write memory holds {got.hex() if got else got}, expected {step[3].hex()}")
            log(f"ok: memory now {got.hex()}")
        else:
            raise MemPatchError(f"unknown step {kind}")


def main(argv=None):
    from a7r.patches import PATCHES

    ap = argparse.ArgumentParser(prog="a7r.mempatch")
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("patch", choices=sorted(PATCHES))
    ap.add_argument("logdir", type=Path)
    args = ap.parse_args(argv)
    patch = PATCHES[args.patch]

    sys.path.insert(0, str(args.pmca_root))
    from pmca.commands.usb import senserShellCommand

    args.logdir.mkdir(parents=True, exist_ok=False)
    lines, done = [], {}

    def log(msg):
        print(msg)
        lines.append(msg)

    def complete(camera):
        camera.readHasp()
        camera.setTerminalEnable(False)
        camera.setTerminalEnable(True)
        try:
            session = TerminalSession(camera.dev, max_polls=6000, poll_delay=0.01)
            session.run("uname -a")
            pids = re.findall(r"^\s*(\d+)\s*$", session.run(f"pidof {PROCESS}"), re.M)
            if len(pids) != 1:
                raise MemPatchError(f"expected one {PROCESS} pid, got {pids}")
            pid = int(pids[0])
            maps = session.run(f"cat /proc/{pid}/maps")
            (args.logdir / "maps.txt").write_text(maps)
            base = find_text_base(maps, patch.file)
            log(f"{PROCESS} pid {pid}, {patch.file} text base {base:#x}")
            run_mempatch(mempatch_steps(patch, pid, base), session, camera, log=log)
            done["ok"] = True
        finally:
            camera.setTerminalEnable(False)
            (args.logdir / "transcript.txt").write_text("\n".join(lines) + "\n")

    senserShellCommand(complete=complete)
    if not done:
        raise SystemExit("mempatch session did not complete; see output above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
