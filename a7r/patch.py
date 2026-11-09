"""Verified byte patches for firmware files the user supplies.

A BytePatch names the target file, the SHA-256 it must have before patching
and a list of (offset, original, replacement) edits of equal length. Nothing
is applied unless the hash and every original byte sequence match, so a patch
can only ever land on the exact firmware build it was written for. Only our
patch descriptions are published, never patched Sony files.

    python -m a7r.patch image-size-aspect-fallback IN.so OUT.so
"""
import argparse
import hashlib
import sys
from dataclasses import dataclass


class PatchError(Exception):
    pass


@dataclass(frozen=True)
class BytePatch:
    name: str
    file: str
    sha256: str
    edits: list

    def __post_init__(self):
        for off, old, new in self.edits:
            if len(old) != len(new):
                raise PatchError(f"{self.name}: edit at {off:#x} changes length")


def apply_patch(patch: BytePatch, data: bytes) -> bytes:
    digest = hashlib.sha256(data).hexdigest()
    if digest != patch.sha256:
        raise PatchError(f"{patch.name}: input sha256 {digest} != expected {patch.sha256}")
    out = bytearray(data)
    for off, old, new in patch.edits:
        if out[off:off + len(old)] != old:
            raise PatchError(f"{patch.name}: original bytes at {off:#x} are {out[off:off + len(old)].hex()}, expected {old.hex()}")
        out[off:off + len(new)] = new
    return bytes(out)


def main(argv=None):
    from a7r.patches import PATCHES

    ap = argparse.ArgumentParser(prog="a7r.patch")
    ap.add_argument("patch", choices=sorted(PATCHES))
    ap.add_argument("input")
    ap.add_argument("output")
    args = ap.parse_args(argv)
    p = PATCHES[args.patch]
    out = apply_patch(p, open(args.input, "rb").read())
    with open(args.output, "wb") as f:
        f.write(out)
    print(f"{p.name}: {len(p.edits)} edit(s) -> {args.output} sha256 {hashlib.sha256(out).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
