"""Build synthetic Backup.bin images for tests (no Sony data involved)."""
import struct

HEADER_SIZE = 0x100


def build_backup(subsystems, revision=4, region=b"UC2", version=b"3.20"):
    """subsystems: list of lists of property specs.

    A spec is None (unused slot), or a tuple (attr, kind, data[, reset]) where
    kind is "fixed", "oversize" or "variable" (variable takes maxSize as 5th).
    """
    entry_fmt = "<HI" if revision >= 4 else "<BI"
    entry_size = struct.calcsize(entry_fmt)
    num_props = sum(len(s) for s in subsystems)
    sub_table = b""
    ptr = 0
    for s in subsystems:
        sub_table += struct.pack("<HI", len(s), ptr)
        ptr += len(s)
    data_offset = HEADER_SIZE + len(sub_table) + num_props * entry_size
    prop_table = b""
    blob = b""
    for s in subsystems:
        for spec in s:
            if spec is None:
                prop_table += struct.pack(entry_fmt, 0, 0xFFFFFFFF)
                continue
            attr, kind, data = spec[:3]
            reset = spec[3] if len(spec) > 3 else None
            off = data_offset + len(blob)
            if kind == "fixed":
                size, max_size, body = len(data), len(data), data
            elif kind == "oversize":
                size, max_size = 0xFF, len(data)
                body = struct.pack("<H", len(data)) + data
            elif kind == "variable":
                max_size = spec[4]
                size = 0
                body = struct.pack("<HH", len(data), max_size) + data.ljust(max_size, b"\0")
            else:
                raise ValueError(kind)
            if reset is not None:
                body += reset.ljust(max_size, b"\0")
            blob += body
            prop_table += struct.pack(entry_fmt, attr, size << 24 | off)
    header = bytearray(HEADER_SIZE)
    struct.pack_into("<III4sIIIII", header, 0, 0x12345678, 0, 0,
                     b"BK%d\0" % revision, len(subsystems), num_props,
                     data_offset, len(blob), 0)
    header[0x40:0x40 + len(version)] = version
    header[0xC0:0xC0 + len(region)] = region
    image = bytearray(bytes(header) + sub_table + prop_table + blob)
    checksum = sum(image[:0x20]) + sum(image[0x24:])
    struct.pack_into("<I", image, 0x20, checksum & 0xFFFFFFFF)
    return bytes(image)
