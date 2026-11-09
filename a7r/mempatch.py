"""Stage 3: patch the running camera process in RAM via /proc/<pid>/mem.

For each edit of a BytePatch (whose file is mapped by the main camera process
im.elf), compute the absolute address from /proc/<pid>/maps and run a7rpoke
(native/a7rpoke, uploaded to RAM): it writes only if the expected original
bytes are there and reads back. The camera's busybox 1.13 dd cannot write to
/proc/<pid>/mem (no conv=notrunc). Nothing touches flash; a power cycle undoes it.
If memory already holds the replacement the edit is skipped.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.mempatch fw/Sony-PMCA-RE libobj-image-size-aspect-fallback work/mempatch-<date>
"""
import argparse
import hashlib
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


POKE_REMOTE = f"{WORK}/a7rpoke"


def mempatch_steps(patch, pid, base, poke):
    steps = [
        ("run", f"mkdir -p {WORK}"),
        ("put", POKE_REMOTE, poke),
        ("run", f"chmod 755 {POKE_REMOTE}"),
    ]
    for off, old, new in patch.edits:
        addr = base + off
        steps += [
            ("read", f"{POKE_REMOTE} /proc/{pid}/mem {addr} --read {len(old)}", old, new),
            ("poke", f"{POKE_REMOTE} /proc/{pid}/mem {addr} {old.hex()} {new.hex()}", new),
        ]
    return steps


def run_mempatch(steps, session, camera, log=print):
    allowed = {s[1] for s in steps if s[0] in ("run", "read", "poke")}
    skip_poke = False

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
        elif kind == "put":
            camera.writeFile(step[1], step[2])
            back = camera.readFile(step[1]) or b""
            if hashlib.sha256(back).digest() != hashlib.sha256(step[2]).digest():
                raise MemPatchError(f"uploaded {step[1]} sha256 mismatch; not running it")
            log(f"ok: {step[1]} uploaded, sha256 {hashlib.sha256(back).hexdigest()}")
        elif kind == "read":
            m = re.search(r"^read ([0-9a-f]+)$", run(step[1]), re.M)
            if not m:
                raise MemPatchError("a7rpoke --read gave no result; tool may not run on this camera")
            got, old, new = bytes.fromhex(m.group(1)), step[2], step[3]
            if got not in (old, new):
                raise MemPatchError(f"memory holds {got.hex()}, expected {old.hex()}; not writing")
            skip_poke = got == new
            log(f"ok: memory holds {got.hex()} ({'already patched' if skip_poke else 'original'})")
        elif kind == "poke":
            if skip_poke:
                log("skip write: already patched")
                continue
            out = run(step[1])
            if re.search(r"^already patched$", out, re.M):
                log("ok: already patched")
            elif re.search(r"^ok$", out, re.M) and f"after {step[2].hex()}" in out:
                log(f"ok: memory now {step[2].hex()}")
            else:
                raise MemPatchError(f"a7rpoke did not confirm the write: {out.strip()}")
        else:
            raise MemPatchError(f"unknown step {kind}")


def main(argv=None):
    from a7r.patches import PATCHES

    ap = argparse.ArgumentParser(prog="a7r.mempatch")
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("patch", choices=sorted(PATCHES))
    ap.add_argument("logdir", type=Path)
    ap.add_argument("--poke", type=Path, default=Path("work/bin/a7rpoke-armv7"),
                    help="a7rpoke built for ARMv7 (see native/a7rpoke)")
    args = ap.parse_args(argv)
    patch = PATCHES[args.patch]
    poke = args.poke.read_bytes()

    sys.path.insert(0, str(args.pmca_root))
    from pmca.commands.usb import senserShellCommand

    args.logdir.mkdir(parents=True, exist_ok=False)
    lines, done = [], {}

    def log(msg):
        print(msg, flush=True)
        lines.append(msg)
        with open(args.logdir / "transcript.txt", "a") as f:  # written as we go: survives a dropped USB link
            f.write(msg + "\n")

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
            run_mempatch(mempatch_steps(patch, pid, base, poke), session, camera, log=log)
            done["ok"] = True
        finally:
            camera.setTerminalEnable(False)

    senserShellCommand(complete=complete)
    if not done:
        raise SystemExit("mempatch session did not complete; see output above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
