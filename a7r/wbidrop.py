"""Invalidate the warm-boot snapshot so the camera cold-boots once.

HIGH RISK, NEVER RUN, NOT PART OF THE CURRENT DIRECTION. It writes a flash
partition that every boot depends on. If the cold boot or the new snapshot
fails, recovery may need a reflash or hardware access. Kept for the record
only; running it needs a separate, explicit decision by the camera's owner.
The shot-counter tables it was meant to rebuild can be changed in RAM
instead (docs/findings/aspect-ratio.md section 10).

The ILCE-7R always resumes from a snapshot image on /dev/nflasha5 ("Warm
Boot Image", partition type 2 in partinf.conf, 60 MiB, header magic "WBI1").
Tables built at init (e.g. the MPR still size table behind the shot counter)
are frozen in that image. Sony's updater invalidates it with
ud_wbi_drop.elf, which writes 512 zero bytes at the start of every type-2
partition; the next boot is a cold boot and a new image is made.

This tool does exactly that with the camera's own busybox, over the service
shell, and nothing else:
  1. check /proc/partitions: nflasha5 has 61440 KiB
  2. save the first 512 bytes of /dev/nflasha5 locally, require "WBI1"
  3. dd if=/dev/zero of=/dev/nflasha5 bs=512 count=1 ; sync
  4. read the header back and require zeros
Afterwards pull the battery (no clean shutdown) and power on.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.wbidrop fw/Sony-PMCA-RE work/wbidrop-<date>
"""
import argparse
import re
import sys
from pathlib import Path

from a7r.stage3 import TerminalSession

WORK = "/android/a7r"
WBI_DEV = "/dev/nflasha5"
WBI_KIB = 61440
MAGIC = b"WBI1"
DROP_CMD = f"dd if=/dev/zero of={WBI_DEV} bs=512 count=1"
READ_BEFORE = f"dd if={WBI_DEV} of={WORK}/wbi_head_before.bin bs=512 count=1"
READ_AFTER = f"dd if={WBI_DEV} of={WORK}/wbi_head_after.bin bs=512 count=1"


class WbiDropError(Exception):
    pass


def check_partitions(text):
    m = re.search(r"^\s*\d+\s+\d+\s+(\d+)\s+nflasha5\s*$", text, re.M)
    if not m:
        raise WbiDropError("nflasha5 not found in /proc/partitions")
    if int(m.group(1)) != WBI_KIB:
        raise WbiDropError(f"nflasha5 has {m.group(1)} KiB, expected {WBI_KIB}")


def wbidrop_steps():
    return [
        ("partitions", "cat /proc/partitions"),
        ("run", f"mkdir -p {WORK}"),
        ("save_head", READ_BEFORE, f"{WORK}/wbi_head_before.bin"),
        ("drop", DROP_CMD),
        ("run", "sync"),
        ("verify", READ_AFTER, f"{WORK}/wbi_head_after.bin"),
    ]


def run_wbidrop(steps, session, camera, outdir, log=print):
    allowed = {s[1] for s in steps}
    state = {"skip": False}

    def run(cmd):
        if cmd not in allowed:
            raise WbiDropError(f"command not allowed: {cmd}")
        log(f"$ {cmd}")
        out = session.run(cmd)
        log(out.rstrip())
        return out

    for step in steps:
        kind = step[0]
        if kind == "partitions":
            check_partitions(run(step[1]))
            log("ok: nflasha5 is the 60 MiB warm boot image partition")
        elif kind == "run":
            if step[1] == "sync" and state["skip"]:
                continue
            run(step[1])
        elif kind == "save_head":
            run(step[1])
            head = camera.readFile(step[2]) or b""
            (Path(outdir) / "wbi_head_before.bin").write_bytes(head)
            if len(head) != 512:
                raise WbiDropError(f"read {len(head)} header bytes, expected 512")
            if head == bytes(512):
                log("header already zero: snapshot already dropped, nothing to write")
                state["skip"] = True
            elif not head.startswith(MAGIC):
                raise WbiDropError(f"header starts with {head[:4]!r}, expected {MAGIC!r}; not writing")
            else:
                log(f"ok: header starts with {MAGIC.decode()}, saved locally")
        elif kind == "drop":
            if not state["skip"]:
                run(step[1])
        elif kind == "verify":
            run(step[1])
            after = camera.readFile(step[2]) or b""
            (Path(outdir) / "wbi_head_after.bin").write_bytes(after)
            if after != bytes(512):
                raise WbiDropError("header is not zero after the drop")
            log("ok: snapshot header is zero; next boot will be a cold boot")
        else:
            raise WbiDropError(f"unknown step {kind}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.wbidrop")
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("logdir", type=Path)
    args = ap.parse_args(argv)

    sys.path.insert(0, str(args.pmca_root))
    from pmca.commands.usb import senserShellCommand

    args.logdir.mkdir(parents=True, exist_ok=False)
    done = {}

    def log(msg):
        print(msg, flush=True)
        with open(args.logdir / "transcript.txt", "a") as f:
            f.write(msg + "\n")

    def complete(camera):
        camera.readHasp()
        camera.setTerminalEnable(False)
        camera.setTerminalEnable(True)
        try:
            session = TerminalSession(camera.dev, max_polls=6000, poll_delay=0.01)
            session.run("uname -a")
            run_wbidrop(wbidrop_steps(), session, camera, args.logdir, log=log)
            done["ok"] = True
        finally:
            camera.setTerminalEnable(False)

    senserShellCommand(complete=complete)
    if not done:
        raise SystemExit("wbidrop session did not complete; see output above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
