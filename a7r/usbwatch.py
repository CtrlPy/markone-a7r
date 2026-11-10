"""See camera restarts from the laptop side, without a session on the camera.

After a service-mode session the camera comes back as USB storage (054c:07c2)
in about a second. When the session is followed by a kernel crash and restart,
it takes 9-12 s (checked against /proc/uptime and /proc/klog for every session
on 2026-11-10). The laptop's kernel log has both events.

    python -m a7r.usbwatch [--since HH:MM:SS]
"""
import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime

SERVICE_PID = "0336"
STORAGE_PID = "07c2"
RESTART_THRESHOLD = 3.0  # seconds; normal return 0.8-1.1 s, restart 9-12 s

_LINE = re.compile(r"(\d\d:\d\d:\d\d\.\d+) .*usb [\d.-]+: (USB disconnect|New USB device found, idVendor=054c, idProduct=([0-9a-f]{4}))")


@dataclass
class Session:
    start: str
    back_after: float | None

    @property
    def restarted(self):
        return None if self.back_after is None else self.back_after > RESTART_THRESHOLD


def _events(journal):
    for line in journal.splitlines():
        m = _LINE.search(line)
        if m:
            kind = "disconnect" if m.group(2) == "USB disconnect" else m.group(3)
            yield datetime.strptime(m.group(1), "%H:%M:%S.%f"), kind


def service_sessions(journal):
    """Every service-mode session in the log with the time the camera took to return as storage."""
    ev = list(_events(journal))
    out = []
    for i, (t, kind) in enumerate(ev):
        if kind != SERVICE_PID:
            continue
        end = next((x for x, k in ev[i + 1:] if k == "disconnect"), None)
        back = next((x for x, k in ev[i + 1:] if k == STORAGE_PID), None)
        gap = (back - end).total_seconds() if end and back and back > end else None
        out.append(Session(t.strftime("%H:%M:%S"), gap))
    return out


def journal_since(since):
    return subprocess.run(["journalctl", "-k", "--since", since, "--no-pager", "-o", "short-precise"],
                          capture_output=True, text=True, check=True).stdout


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.usbwatch", description="List service sessions and restarts")
    ap.add_argument("--since", default="today")
    args = ap.parse_args(argv)
    for s in service_sessions(journal_since(args.since)):
        state = "no return yet" if s.back_after is None else (
            f"back after {s.back_after:4.1f} s  {'RESTART' if s.restarted else 'ok'}")
        print(f"{s.start}  {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
