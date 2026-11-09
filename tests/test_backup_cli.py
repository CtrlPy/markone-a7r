import subprocess
import sys

from tests.bkbuilder import build_backup


def test_dump_piped_into_head_exits_quietly(tmp_path):
    f = tmp_path / "Backup.bin"
    f.write_bytes(build_backup([[(0, "fixed", b"\x01")] * 50000]))
    proc = subprocess.run(
        f"{sys.executable} -m a7r.backup dump {f} | head -1",
        shell=True, capture_output=True, text=True)
    assert proc.stdout.startswith("# BK4")
    assert "BrokenPipeError" not in proc.stderr
