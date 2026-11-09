"""Recover BKID name -> Backup.bin property id tables from firmware ELF files.

Some libraries (e.g. lib/libmprctrl.so) keep a table of 8-byte entries
{uint32 id; const char *name;} for their Backup.bin properties. Every word in
the file that points at a "BKID_..." string and is preceded by a plausible id
(subsystem below the template's subsystem count) is taken as an entry.

The layout was checked on ILCE-7R 3.20: read this way, 710 of 711 names resolve
and every JPEG size estimate obeys MAX >= TGT and EXFINE > FINE > STD; read as
{name, id} only 697 resolve and the estimates contradict each other.

Usage:
    python -m a7r.bkid ELF BACKUP.bin [--grep REGEX]
"""
import argparse
import re
import struct
import sys

NAME_RE = re.compile(rb"BKID_[A-Z0-9_]+\x00")


def find_name_id_pairs(raw: bytes, segments, max_subsystem: int, name_re=NAME_RE):
    """segments: iterable of (file_offset, vaddr, filesz) for loaded segments."""
    segments = list(segments)

    def off2va(off):
        for f_off, va, size in segments:
            if f_off <= off < f_off + size:
                return va + off - f_off
        return None

    names = {}
    for m in name_re.finditer(raw):
        va = off2va(m.start())
        if va is not None:
            names[va] = m.group()[:-1].decode()

    pairs = {}
    for i in range(0, len(raw) - 7, 4):
        pid, ptr = struct.unpack_from("<II", raw, i)
        name = names.get(ptr)
        if name and pid >> 16 < max_subsystem:
            pairs.setdefault(name, pid)
    return pairs


def elf_load_segments(path):
    from elftools.elf.elffile import ELFFile

    with open(path, "rb") as f:
        return [(s["p_offset"], s["p_vaddr"], s["p_filesz"])
                for s in ELFFile(f).iter_segments() if s["p_type"] == "PT_LOAD"]


def main(argv=None):
    from a7r.backup import BackupFile

    ap = argparse.ArgumentParser(prog="a7r.bkid", description="Map BKID names to Backup.bin ids")
    ap.add_argument("elf")
    ap.add_argument("backup", help="a Backup.bin, used for the subsystem count and values")
    ap.add_argument("--grep", default="")
    args = ap.parse_args(argv)

    bk = BackupFile(open(args.backup, "rb").read())
    raw = open(args.elf, "rb").read()
    pairs = find_name_id_pairs(raw, elf_load_segments(args.elf), bk.num_subsystems)
    pattern = re.compile(args.grep)
    for name, pid in sorted(pairs.items(), key=lambda kv: kv[1]):
        if not pattern.search(name):
            continue
        p = bk.properties.get(pid)
        value = p.data.hex() if p else "-"
        print(f"{pid:#010x} {name} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
