"""Plan Backup.bin values that give a hidden aspect real still geometry.

The camera stores, per aspect and image size, the output pixel size
(PXSZ: u16 width, u16 height, u32 width*height) and JPEG size estimates
(DATSZ: u32, used for the shot counter and buffers). On the ILCE-7R the 1:1
slots exist but are zero. plan_square() derives them from the camera's own
3:2 values:

- PXSZ: a centred square using the full 3:2 height, side rounded down to a
  multiple of 16 (every width Sony ships is a multiple of 16).
- DATSZ: the 3:2 estimate scaled by the pixel-count ratio, rounded up.
- DATSZ_JPGSCN (embedded screennail estimate): copied from 3:2. The shot
  counter reads it; left at zero the camera reports "no space" (seen on
  camera 2026-11-09). Over-estimating only lowers the shot counter.

    python -m a7r.formats square dumps/<dir>/after.bin plan.json
"""
import argparse
import json
import math
import struct
import sys

from a7r.backup import BackupFile
from a7r.ids import IDS

SIZES = ("L", "M", "S")
PREFIXES = ("", "APSC_")
QUALITIES = ("STD", "FINE", "EXFINE")
KINDS = ("TGT", "MAX")


def encode_pxsz(width, height):
    return struct.pack("<HHI", width, height, width * height)


def decode_pxsz(data):
    w, h, n = struct.unpack("<HHI", data)
    if n != w * h:
        raise ValueError(f"inconsistent PXSZ {w}x{h} != {n}")
    return w, h


def square_side(height):
    return height // 16 * 16


def _u32(bk, name):
    return struct.unpack("<I", bk.properties[IDS[name]].data)[0]


def plan_square(bk: BackupFile):
    planned = {}
    for prefix in PREFIXES:
        for size in SIZES:
            src = f"PXSZ_{prefix}STL_{size}_3_2"
            w, h = decode_pxsz(bk.properties[IDS[src]].data)
            if not w or not h:
                raise ValueError(f"{src} is empty, cannot derive 1:1")
            side = square_side(h)
            planned[IDS[f"PXSZ_{prefix}STL_{size}_1_1"]] = encode_pxsz(side, side)
            ratio = side * side / (w * h)
            for q in QUALITIES:
                for k in KINDS:
                    value = _u32(bk, f"DATSZ_{prefix}JPG_{size}_3_2_{q}_{k}")
                    if not value:
                        raise ValueError(f"DATSZ_{prefix}JPG_{size}_3_2_{q}_{k} is empty")
                    planned[IDS[f"DATSZ_{prefix}JPG_{size}_1_1_{q}_{k}"]] = struct.pack("<I", math.ceil(value * ratio))
    for k in KINDS:
        value = _u32(bk, f"DATSZ_JPGSCN_3_2_{k}")
        if not value:
            raise ValueError(f"DATSZ_JPGSCN_3_2_{k} is empty")
        planned[IDS[f"DATSZ_JPGSCN_1_1_{k}"]] = struct.pack("<I", value)
    return planned


def xpan_height(width):
    """Hasselblad XPan 65:24, height rounded to the nearest multiple of 16."""
    return round(width * 24 / 65 / 16) * 16


def plan_xpan(bk: BackupFile):
    """XPan geometry for the 16:9 slot: full 3:2 width, 65:24 height.

    JPEG size estimates scale from the 3:2 ones by pixel count; the 16:9
    screennail estimate is left as it is.
    """
    planned = {}
    for prefix in PREFIXES:
        for size in SIZES:
            src = f"PXSZ_{prefix}STL_{size}_3_2"
            w, h = decode_pxsz(bk.properties[IDS[src]].data)
            if not w or not h:
                raise ValueError(f"{src} is empty, cannot derive XPan")
            xh = xpan_height(w)
            planned[IDS[f"PXSZ_{prefix}STL_{size}_16_9"]] = encode_pxsz(w, xh)
            ratio = xh / h
            for q in QUALITIES:
                for k in KINDS:
                    value = _u32(bk, f"DATSZ_{prefix}JPG_{size}_3_2_{q}_{k}")
                    if not value:
                        raise ValueError(f"DATSZ_{prefix}JPG_{size}_3_2_{q}_{k} is empty")
                    planned[IDS[f"DATSZ_{prefix}JPG_{size}_16_9_{q}_{k}"]] = struct.pack("<I", math.ceil(value * ratio))
    return planned


def describe(planned):
    names = {v: k for k, v in IDS.items()}
    rows = []
    for pid in sorted(planned):
        name, data = names[pid], planned[pid]
        if name.startswith("PXSZ"):
            w, h = decode_pxsz(data)
            rows.append((pid, name, f"{w}x{h} ({w * h / 1e6:.1f} MP)"))
        else:
            rows.append((pid, name, str(struct.unpack("<I", data)[0])))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.formats")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("square", "plan 1:1 geometry from a camera Backup.bin"),
                        ("xpan", "plan XPan 65:24 geometry in the 16:9 slot")):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("backup")
        sp.add_argument("plan")
    args = ap.parse_args(argv)
    planner = {"square": plan_square, "xpan": plan_xpan}[args.cmd]
    planned = planner(BackupFile(open(args.backup, "rb").read()))
    with open(args.plan, "w") as f:
        json.dump({f"{k:#010x}": v.hex() for k, v in sorted(planned.items())}, f, indent=2)
        f.write("\n")
    for pid, name, value in describe(planned):
        print(f"{pid:#010x}  {name:32s} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
