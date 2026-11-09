"""Stage 3: RAM-only overlay of a patched camera library (service shell).

Copies a patched library into /android/a7r (tmpfs) and bind-mounts it over
/usr/lib/<lib>. Nothing is written to flash; a power cycle (or `undo`)
removes the overlay. The overlay is only applied when the library is not
loaded by any process yet, so the camera picks it up on the next dlopen.

Only these shell commands may change state, and only for libraries that have
a patch in a7r.patches: `mkdir -p /android/a7r`, `mount -o bind ...`,
`umount /usr/lib/<lib>`. Everything else must pass stage3.is_read_only().

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.overlay apply fw/Sony-PMCA-RE image-size-aspect-fallback work/patched/<lib> work/overlay-<date>
    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.overlay undo  fw/Sony-PMCA-RE image-size-aspect-fallback - work/overlay-undo-<date>
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

from a7r.stage3 import TerminalSession, is_read_only

REMOTE_DIR = "/android/a7r"


class OverlayError(Exception):
    pass


def _patched_files():
    from a7r.patches import PATCHES
    return {p.file for p in PATCHES.values()}


def write_commands(lib):
    if lib not in _patched_files():
        raise OverlayError(f"{lib} has no patch description; refusing to overlay it")
    return {
        f"mkdir -p {REMOTE_DIR}",
        f"mount -o bind {REMOTE_DIR}/{lib} /usr/lib/{lib}",
        f"umount /usr/lib/{lib}",
    }


def _stem(lib):
    return lib.rsplit(".so", 1)[0]


def overlay_steps(lib, data):
    write_commands(lib)  # validates lib
    remote = f"{REMOTE_DIR}/{lib}"
    digest = hashlib.sha256(data).hexdigest()
    return [
        ("check_unloaded", f"grep -l {_stem(lib)} /proc/*/maps"),
        ("run", f"mkdir -p {REMOTE_DIR}"),
        ("write", remote, data),
        ("verify_file", remote, digest),
        ("run", f"mount -o bind {remote} /usr/lib/{lib}"),
        ("check_mounted", f"/usr/lib/{lib}", True),
    ]


def undo_steps(lib):
    write_commands(lib)
    return [
        ("run", f"umount /usr/lib/{lib}"),
        ("check_mounted", f"/usr/lib/{lib}", False),
    ]


def _run(session, cmd, lib):
    if cmd not in write_commands(lib) and not is_read_only(cmd):
        raise OverlayError(f"command not allowed: {cmd}")
    return session.run(cmd)


def run_steps(steps, session, camera, lib=None, log=print):
    lib = lib or next(s[1].rsplit("/", 1)[1] for s in steps if s[0] in ("check_mounted",))
    for step in steps:
        kind = step[0]
        if kind == "check_unloaded":
            out = _run(session, step[1], lib)
            hits = re.findall(r"^/proc/\d+/maps$", out, re.M)
            if hits:
                raise OverlayError(f"{lib} is already loaded ({', '.join(hits)}); power-cycle the camera and retry")
            log(f"ok: {lib} not loaded")
        elif kind == "run":
            log(f"$ {step[1]}")
            log(_run(session, step[1], lib).rstrip())
        elif kind == "write":
            log(f"writing {len(step[2])} bytes to {step[1]}")
            camera.writeFile(step[1], step[2])
        elif kind == "verify_file":
            back = camera.readFile(step[1])
            got = hashlib.sha256(back or b"").hexdigest()
            if got != step[2]:
                raise OverlayError(f"read-back sha256 {got} != {step[2]}; not binding")
            log(f"ok: read-back sha256 {got}")
        elif kind == "check_mounted":
            mounts = _run(session, "cat /proc/mounts", lib)
            visible = f" {step[1]} " in mounts
            if visible != step[2]:
                raise OverlayError(f"mount of {step[1]} {'not visible' if step[2] else 'still visible'} in /proc/mounts")
            log(f"ok: {step[1]} {'mounted' if step[2] else 'unmounted'}")
        else:
            raise OverlayError(f"unknown step {kind}")


def main(argv=None):
    from a7r.patch import apply_patch
    from a7r.patches import PATCHES

    ap = argparse.ArgumentParser(prog="a7r.overlay")
    ap.add_argument("action", choices=["apply", "undo"])
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("patch", choices=sorted(PATCHES))
    ap.add_argument("patched", help="patched library file (apply) or - (undo)")
    ap.add_argument("logdir", type=Path)
    ap.add_argument("--original", type=Path, help="original library, to re-check the patched file")
    args = ap.parse_args(argv)

    patch = PATCHES[args.patch]
    lib = patch.file
    if args.action == "apply":
        data = Path(args.patched).read_bytes()
        if args.original:
            expected = apply_patch(patch, args.original.read_bytes())
            if expected != data:
                raise OverlayError("patched file does not match original + patch")
        steps = overlay_steps(lib, data)
    else:
        steps = undo_steps(lib)

    sys.path.insert(0, str(args.pmca_root))
    from pmca.commands.usb import senserShellCommand

    args.logdir.mkdir(parents=True, exist_ok=False)
    lines = []
    done = {}

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
            session = TerminalSession(camera.dev, max_polls=4000, poll_delay=0.01)
            session.run("uname -a")
            run_steps(steps, session, camera, lib=lib, log=log)
            done["ok"] = True
        finally:
            camera.setTerminalEnable(False)

    senserShellCommand(complete=complete)
    if not done:
        raise SystemExit("overlay session did not complete; see output above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
