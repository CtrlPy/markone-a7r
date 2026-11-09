import pytest

from a7r.stage3 import RECON_COMMANDS, TerminalSession, is_read_only


class FakeTerminal:
    """Echoes like a shell: each written line is answered with its output then a prompt."""

    def __init__(self, outputs):
        self.outputs = outputs
        self.pending = b""
        self.written = []

    def writeTerminal(self, data):
        self.written.append(data)
        line = data.decode().strip()
        if line.startswith("echo __A7R_"):
            self.pending += data + line[5:].replace("''", "").encode() + b"\r\n# "
        else:
            self.pending += data + self.outputs.get(line, b"") + b"# "

    def readTerminal(self):
        chunk, self.pending = self.pending[:7], self.pending[7:]
        return chunk


def test_run_returns_only_the_command_output():
    term = FakeTerminal({"uname -a": b"Linux 3.0.27 armv7l\r\n"})
    out = TerminalSession(term, max_polls=1000).run("uname -a")
    assert out.strip() == "Linux 3.0.27 armv7l"


def test_each_command_gets_its_own_marker():
    term = FakeTerminal({"a": b"1\r\n", "b": b"2\r\n"})
    s = TerminalSession(term, max_polls=1000)
    assert s.run("a").strip() == "1"
    assert s.run("b").strip() == "2"


def test_run_times_out_without_marker():
    class Silent:
        def writeTerminal(self, d): pass
        def readTerminal(self): return b""
    with pytest.raises(TimeoutError):
        TerminalSession(Silent(), max_polls=5).run("ps")


@pytest.mark.parametrize("cmd", ["pidof im.elf", "dmesg", "uname -a", "ps", "cat /proc/123/maps", "grep -l libObj /proc/*/maps", "busybox --list", "ls -l /proc/self/mem"])
def test_read_only_commands_pass(cmd):
    assert is_read_only(cmd)


@pytest.mark.parametrize("cmd", ["rm -rf /", "dd if=/dev/zero of=/dev/nflasha", "echo 1 > /proc/x", "cat a >> b", "mount -o remount,rw /", "dmesg -c", "dmesg -n 1", "kill 1", "reboot", "ps; rm x", "a && b", "sh -c x", "$(rm x)", "`rm x`"])
def test_write_or_compound_commands_fail(cmd):
    assert not is_read_only(cmd)


def test_recon_commands_are_all_read_only():
    assert RECON_COMMANDS and all(is_read_only(c) for c in RECON_COMMANDS)


def test_cli_rejects_custom_write_command_before_touching_camera():
    from a7r.stage3 import main
    with pytest.raises(ValueError, match="read-only"):
        main(["fw/Sony-PMCA-RE", "/nonexistent/out", "--cmd", "rm /tmp/x"])
