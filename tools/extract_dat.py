#!/usr/bin/env python3
"""Carve FirmwareData_*.dat out of a Sony "System Software Updater Package" .exe.

Sony re-released old updaters (e.g. Update_ILCE7RV320.exe, packaged 2023-01-30)
in a new uncompressed wrapper that fwtool.py does not recognise
("Exception: Unknown exe file"). The DAT is stored as-is inside the overlay,
so we find its magic and walk its chunks (DATV, PROV, UDID, FDAT, DEND).

Usage:
    python3 tools/extract_dat.py Update_ILCE7RV320.exe FirmwareData_ILCE7RV320.dat
    python3 fwtool.py unpack -f FirmwareData_ILCE7RV320.dat -o out/
"""
import struct
import sys

MAGIC = b"\x89\x55\x46\x55\x0d\x0a\x1a\x0a"


def main(src, dst):
    data = open(src, "rb").read()
    start = data.find(MAGIC)
    if start < 0:
        sys.exit("DAT magic not found")
    if data.count(MAGIC) != 1:
        print("warning: more than one DAT magic found, using the first")
    pos = start + len(MAGIC)
    while True:
        size, typ = struct.unpack_from(">I4s", data, pos)
        print(f"chunk {typ.decode(errors='replace')} size {size}")
        pos += 8 + size
        if typ == b"DEND":
            break
        if pos > len(data):
            sys.exit("ran past end of file, not a valid DAT")
    with open(dst, "wb") as f:
        f.write(data[start:pos])
    print(f"wrote {dst} ({pos - start} bytes, from offset {start:#x})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
