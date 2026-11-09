"""a7rpoke is compiled for the host with zig and exercised on a scratch file."""
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "native" / "a7rpoke" / "a7rpoke.c"
ZIG = ["mise", "exec", "zig@0.13.0", "--", "zig"]

pytestmark = pytest.mark.skipif(shutil.which("mise") is None, reason="needs mise + zig")


@pytest.fixture(scope="module")
def poke(tmp_path_factory):
    out = tmp_path_factory.mktemp("bin") / "a7rpoke"
    subprocess.run(ZIG + ["cc", "-O2", "-Wall", "-Werror", "-o", str(out), str(SRC)], check=True)
    return out


def target(tmp_path, content=bytes(range(32))):
    f = tmp_path / "mem"
    f.write_bytes(content)
    return f


def run(poke, *args):
    return subprocess.run([str(poke), *map(str, args)], capture_output=True, text=True)


def test_writes_when_original_matches(poke, tmp_path):
    f = target(tmp_path)
    r = run(poke, f, 4, "04050607", "aabbccdd")
    assert r.returncode == 0, r.stderr
    assert f.read_bytes()[4:8] == bytes.fromhex("aabbccdd")
    assert "ok" in r.stdout


def test_refuses_and_leaves_file_when_original_differs(poke, tmp_path):
    f = target(tmp_path)
    r = run(poke, f, 4, "deadbeef", "aabbccdd")
    assert r.returncode == 2
    assert f.read_bytes() == bytes(range(32))
    assert "04050607" in r.stdout


def test_already_patched_is_success_without_write(poke, tmp_path):
    f = target(tmp_path)
    r = run(poke, f, 4, "deadbeef", "04050607")
    assert r.returncode == 0
    assert "already" in r.stdout


def test_rejects_length_mismatch_and_bad_hex(poke, tmp_path):
    f = target(tmp_path)
    assert run(poke, f, 4, "0405", "aabbcc").returncode == 1
    assert run(poke, f, 4, "zz", "aa").returncode == 1
    assert f.read_bytes() == bytes(range(32))


def test_read_only_mode_prints_bytes(poke, tmp_path):
    f = target(tmp_path)
    r = run(poke, f, 8, "--read", 4)
    assert r.returncode == 0
    assert r.stdout.strip().endswith("08090a0b")
