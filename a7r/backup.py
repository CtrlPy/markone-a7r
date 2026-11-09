"""Read-only parser for Sony Backup.bin (camera settings store, revisions BK2/BK4).

Format as documented by ma1co/Sony-PMCA-RE (pmca/backup). Little endian:

    0x000 header (0x100 bytes): magic, cookie, writeComp, revision "BKn\\0",
          numSubsystems, numProperties, dataOffset, dataSize, checksum@0x20,
          id1@0x28, version@0x40 (0x20), region@0xC0 (0x20)
    0x100 subsystem table: numSubsystems x (u16 numProperties, u32 firstIndex)
          property table:  numProperties x (attr u16|u8, u32 ptr)
    dataOffset: property data

Property id = subsystem << 16 | index. ptr = size << 24 | offset; size 0xFF
means a u16 size prefix, size 0 means u16 size + u16 maxSize prefix.
If attr & 0x74 the reset (default) value follows the data at offset + maxSize.

Usage:
    python -m a7r.backup dump FILE [--grep SUBSYS]
    python -m a7r.backup diff A B
"""
import argparse
import struct
import sys
from dataclasses import dataclass

HEADER_SIZE = 0x100
UNUSED = 0xFFFFFFFF

ATTR_READ_ONLY = 0x01
ATTR_PROTECTED = 0x02
ATTR_CALLBACK = 0x08
ATTR_RESETTABLE = 0x74
ATTR_ARRAY = 0x80


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class Property:
    id: int
    attr: int
    data: bytes
    max_size: int
    reset: bytes | None

    @property
    def read_only(self):
        return bool(self.attr & ATTR_READ_ONLY)


class BackupFile:
    def __init__(self, image: bytes):
        self.image = bytes(image)
        if len(self.image) < HEADER_SIZE:
            raise BackupError("not a backup file: too short")
        (self.magic, _cookie, _wc, rev, self.num_subsystems, self.num_properties,
         self.data_offset, self.data_size, checksum) = struct.unpack_from("<III4sIIIII", self.image)
        if rev[:2] != b"BK" or rev[3:] != b"\0" or rev[2:3] not in (b"2", b"4"):
            raise BackupError(f"not a backup file: revision {rev!r}")
        self.revision = int(rev[2:3])
        self.size = self.data_offset + self.data_size
        if self.size > len(self.image):
            raise BackupError("truncated backup file")
        body = self.image[:self.size]
        if (sum(body[:0x20]) + sum(body[0x24:])) & 0xFFFFFFFF != checksum:
            raise BackupError("wrong checksum")
        self.version = _cstr(self.image[0x40:0x60])
        self.region = _cstr(self.image[0xC0:0xE0])
        self._entry_fmt = "<HI" if self.revision >= 4 else "<BI"
        self._entry_size = struct.calcsize(self._entry_fmt)
        self._prop_table = HEADER_SIZE + self.num_subsystems * 6
        if self._prop_table + self.num_properties * self._entry_size > self.data_offset:
            raise BackupError("invalid data offset")
        self.properties = dict(self._iter_properties())

    def _iter_properties(self):
        for sub in range(self.num_subsystems):
            count, first = struct.unpack_from("<HI", self.image, HEADER_SIZE + sub * 6)
            if first + count > self.num_properties:
                raise BackupError(f"invalid subsystem {sub:#x}")
            for idx in range(count):
                attr, ptr = struct.unpack_from(
                    self._entry_fmt, self.image, self._prop_table + (first + idx) * self._entry_size)
                if ptr == UNUSED:
                    continue
                pid = sub << 16 | idx
                yield pid, self._read(pid, attr, ptr)

    def _read(self, pid, attr, ptr):
        size, offset = ptr >> 24, ptr & 0xFFFFFF
        if offset < self.data_offset:
            raise BackupError(f"{pid:#010x}: offset before data area")
        max_size = size
        if size == 0xFF:
            (size,) = struct.unpack_from("<H", self.image, offset)
            max_size = size
            offset += 2
        elif size == 0:
            size, max_size = struct.unpack_from("<HH", self.image, offset)
            offset += 4
        if size > max_size or offset + max_size > self.size:
            raise BackupError(f"{pid:#010x}: invalid size")
        data = self.image[offset:offset + size]
        reset = None
        if attr & ATTR_RESETTABLE:
            reset = self.image[offset + max_size:offset + max_size + size]
        return Property(pid, attr, data, max_size, reset)


def diff(a: BackupFile, b: BackupFile):
    """Yield (id, old_data, new_data) for every property whose value differs."""
    for pid in sorted(a.properties.keys() | b.properties.keys()):
        old = a.properties.get(pid)
        new = b.properties.get(pid)
        old_data = old.data if old else None
        new_data = new.data if new else None
        if old_data != new_data:
            yield pid, old_data, new_data


def _cstr(raw):
    return raw.split(b"\0", 1)[0].decode("latin1")


def _hex(data):
    return "-" if data is None else data.hex()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.backup", description="Inspect Sony Backup.bin files")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("file")
    d.add_argument("--subsystem", type=lambda s: int(s, 0))
    x = sub.add_parser("diff")
    x.add_argument("a")
    x.add_argument("b")
    args = ap.parse_args(argv)

    if args.cmd == "dump":
        bk = BackupFile(open(args.file, "rb").read())
        print(f"# BK{bk.revision} region={bk.region} version={bk.version} "
              f"subsystems={bk.num_subsystems} properties={len(bk.properties)}")
        for pid, p in bk.properties.items():
            if args.subsystem is not None and pid >> 16 != args.subsystem:
                continue
            reset = "" if p.reset is None else f" reset={p.reset.hex()}"
            print(f"{pid:#010x} attr={p.attr:#04x} size={len(p.data)} data={p.data.hex()}{reset}")
    else:
        a = BackupFile(open(args.a, "rb").read())
        b = BackupFile(open(args.b, "rb").read())
        for pid, old, new in diff(a, b):
            print(f"{pid:#010x} {_hex(old)} -> {_hex(new)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # output piped into head/less that exited early
        sys.stdout = None
        sys.exit(0)
