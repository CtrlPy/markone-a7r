"""Stage 3 reconnaissance: read-only shell commands on the running camera.

Switches the camera to Sony service ("senser") mode with Sony-PMCA-RE, which
exposes a terminal of the running Linux system over USB, then runs a fixed
list of read-only commands and saves their output. Every command must pass
is_read_only(): one command, no redirection, pipes, chaining or substitution,
and only allow-listed programs.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.stage3 fw/Sony-PMCA-RE work/recon-<date>
"""
import argparse
import re
import shlex
import sys
import time
from pathlib import Path

READ_ONLY_PROGRAMS = {"uname", "cat", "ps", "ls", "grep", "busybox", "id", "which", "head", "df", "free", "readlink"}
FORBIDDEN = re.compile(r"[;&|<>`]|\$\(")

RECON_COMMANDS = [
    "uname -a",
    "cat /proc/version",
    "id",
    "cat /proc/cpuinfo",
    "cat /proc/mounts",
    "ps",
    "busybox --list",
    "which gdbserver strace gdb",
    "ls -l /proc/self/mem",
    "grep -l cmn_view_processDataMgr /proc/1/maps /proc/2/maps",
    "grep -l cmn_view_processDataMgr /proc/*/maps",
    "grep -l libmprctrl /proc/*/maps",
]


def is_read_only(cmd):
    if FORBIDDEN.search(cmd):
        return False
    try:
        words = shlex.split(cmd)
    except ValueError:
        return False
    return bool(words) and words[0] in READ_ONLY_PROGRAMS


class TerminalSession:
    """Run one command at a time on a senser terminal and return its output.

    After each command an end marker is echoed. The marker is written with an
    empty quote pair inside (E''ND) so the terminal's echo of the typed line
    never matches; only the shell's output does.
    """

    def __init__(self, terminal, max_polls=2000, poll_delay=0.0):
        self.term = terminal
        self.max_polls = max_polls
        self.poll_delay = poll_delay
        self.n = 0

    def run(self, cmd):
        self.n += 1
        marker = f"__A7R_END_{self.n}__"
        self.term.writeTerminal(cmd.encode() + b"\n")
        self.term.writeTerminal(f"echo __A7R_E''ND_{self.n}__\n".encode())
        buf = b""
        for _ in range(self.max_polls):
            buf += self.term.readTerminal() or b""
            text = buf.decode("latin1")
            if marker in text:
                return self._clean(text[:text.index(marker)], cmd)
            if self.poll_delay:
                time.sleep(self.poll_delay)
        raise TimeoutError(f"no end marker for {cmd!r}")

    @staticmethod
    def _clean(text, cmd):
        lines = []
        for line in text.replace("\r", "").split("\n"):
            bare = line.lstrip("# ").strip()
            if bare == cmd.strip() or "__A7R_E''ND_" in line or bare == "":
                continue
            lines.append(line.lstrip("# ") if line.startswith("# ") else line)
        return "\n".join(lines) + "\n"


def run(pmca_root, outdir, commands=RECON_COMMANDS):
    for c in commands:
        if not is_read_only(c):
            raise ValueError(f"refusing non read-only command: {c}")
    sys.path.insert(0, str(pmca_root))
    from pmca.commands.usb import senserShellCommand

    outdir.mkdir(parents=True, exist_ok=False)
    done = {}

    def complete(camera):
        camera.readHasp()
        camera.setTerminalEnable(False)
        camera.setTerminalEnable(True)
        try:
            session = TerminalSession(camera.dev, max_polls=4000, poll_delay=0.01)
            session.run("id")  # flush banner
            for i, c in enumerate(commands):
                print(f"$ {c}")
                try:
                    out = session.run(c)
                except TimeoutError as e:
                    out = f"[timeout] {e}\n"
                (outdir / f"{i:02d}.txt").write_text(f"$ {c}\n{out}")
                print(out[:2000])
            done["ok"] = True
        finally:
            camera.setTerminalEnable(False)

    senserShellCommand(complete=complete)
    if not done:
        raise SystemExit("Service shell session did not run; see output above.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.stage3", description="Read-only recon via service shell")
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("outdir", type=Path)
    args = ap.parse_args(argv)
    run(args.pmca_root, args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
