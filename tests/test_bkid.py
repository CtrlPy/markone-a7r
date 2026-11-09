import struct

from a7r.bkid import find_name_id_pairs


def blob_with_table():
    strings = b"junk\0BKID_FOO\0BKID_BAR_1_1\0BKID_ORPHAN\0"
    base = 0x100
    foo, bar, orphan = (base + strings.index(n) for n in (b"BKID_FOO", b"BKID_BAR_1_1", b"BKID_ORPHAN"))
    # Entries are {uint32 id; const char *name;}
    table = struct.pack("<8I", 0x00050014, foo, 0x00050218, bar,
                        0x7FFF0000, orphan,  # subsystem out of range: ignored
                        0x00010001, 0xDEADBEEF)  # not a name pointer: ignored
    raw = bytearray(0x400)
    raw[base:base + len(strings)] = strings
    raw[0x300:0x300 + len(table)] = table
    return bytes(raw)


def test_maps_names_to_ids_from_pointer_pairs():
    identity = [(0, 0, 0x400)]
    pairs = find_name_id_pairs(blob_with_table(), identity, max_subsystem=403)
    assert pairs == {"BKID_FOO": 0x00050014, "BKID_BAR_1_1": 0x00050218}


def test_translates_file_offsets_through_load_segments():
    raw = bytearray(blob_with_table())
    # Same layout but the image is loaded at 0x8000: pointers are virtual addresses.
    for i in range(0x304, 0x320, 8):
        (ptr,) = struct.unpack_from("<I", raw, i)
        struct.pack_into("<I", raw, i, ptr + 0x8000)
    pairs = find_name_id_pairs(bytes(raw), [(0, 0x8000, 0x400)], max_subsystem=403)
    assert pairs["BKID_BAR_1_1"] == 0x00050218
