import math
import struct

import pytest

from a7r.backup import BackupFile
from a7r.formats import decode_pxsz, encode_pxsz, plan_square, square_side
from a7r.ids import IDS
from tests.bkbuilder import build_backup

SENSOR = {"L": (7360, 4912), "M": (4800, 3200), "S": (3680, 2456)}
APSC = {"L": (4800, 3200), "M": (3680, 2456), "S": (2400, 1600)}


def camera_like_backup():
    values = {}
    for prefix, dims in (("", SENSOR), ("APSC_", APSC)):
        for size, (w, h) in dims.items():
            values[IDS[f"PXSZ_{prefix}STL_{size}_3_2"]] = encode_pxsz(w, h)
            values[IDS[f"PXSZ_{prefix}STL_{size}_1_1"]] = bytes(8)
            for i, q in enumerate(("STD", "FINE", "EXFINE")):
                for j, k in enumerate(("TGT", "MAX")):
                    values[IDS[f"DATSZ_{prefix}JPG_{size}_3_2_{q}_{k}"]] = struct.pack("<I", 1000 * (i + 1) + 100 * j + 7)
                    values[IDS[f"DATSZ_{prefix}JPG_{size}_1_1_{q}_{k}"]] = bytes(4)
    values[IDS["DATSZ_JPGSCN_3_2_MAX"]] = struct.pack("<I", 1171)
    values[IDS["DATSZ_JPGSCN_3_2_TGT"]] = struct.pack("<I", 853)
    values[IDS["DATSZ_JPGSCN_1_1_MAX"]] = bytes(4)
    values[IDS["DATSZ_JPGSCN_1_1_TGT"]] = bytes(4)
    top = max(values) & 0xFFFF
    sub5 = [(0, "fixed", values[0x00050000 | i]) if (0x00050000 | i) in values else None for i in range(top + 1)]
    return BackupFile(build_backup([[], [], [], [], [], sub5]))


def test_pxsz_roundtrip():
    assert decode_pxsz(encode_pxsz(7360, 4912)) == (7360, 4912)
    assert encode_pxsz(4, 3)[4:] == struct.pack("<I", 12)


def test_decode_pxsz_rejects_inconsistent_pixel_count():
    with pytest.raises(ValueError):
        decode_pxsz(struct.pack("<HHI", 10, 10, 99))


@pytest.mark.parametrize("h, side", [(4912, 4912), (3200, 3200), (2456, 2448), (1600, 1600)])
def test_square_side_is_largest_multiple_of_16_within_height(h, side):
    assert square_side(h) == side


def test_plan_square_fills_all_1_1_geometry_from_3_2():
    planned = plan_square(camera_like_backup())
    assert len(planned) == 44
    assert decode_pxsz(planned[IDS["PXSZ_STL_L_1_1"]]) == (4912, 4912)
    assert decode_pxsz(planned[IDS["PXSZ_STL_M_1_1"]]) == (3200, 3200)
    assert decode_pxsz(planned[IDS["PXSZ_STL_S_1_1"]]) == (2448, 2448)
    assert decode_pxsz(planned[IDS["PXSZ_APSC_STL_L_1_1"]]) == (3200, 3200)
    assert decode_pxsz(planned[IDS["PXSZ_APSC_STL_S_1_1"]]) == (1600, 1600)


def test_plan_square_scales_jpeg_estimates_by_pixel_count_rounding_up():
    planned = plan_square(camera_like_backup())
    got = struct.unpack("<I", planned[IDS["DATSZ_JPG_L_1_1_FINE_MAX"]])[0]
    assert got == math.ceil(2107 * 4912 * 4912 / (7360 * 4912))


def test_plan_square_only_touches_1_1_ids():
    planned = plan_square(camera_like_backup())
    names = {v: k for k, v in IDS.items()}
    assert all("_1_1" in names[pid] for pid in planned)


def test_plan_square_refuses_when_3_2_source_is_empty():
    bk = camera_like_backup()
    bk.properties[IDS["PXSZ_STL_L_3_2"]] = bk.properties[IDS["PXSZ_STL_L_3_2"]].__class__(
        IDS["PXSZ_STL_L_3_2"], 0, bytes(8), 8, None)
    with pytest.raises(ValueError, match="3_2"):
        plan_square(bk)


def test_plan_square_copies_screennail_estimate_from_3_2():
    planned = plan_square(camera_like_backup())
    assert struct.unpack("<I", planned[IDS["DATSZ_JPGSCN_1_1_MAX"]])[0] == 1171
    assert struct.unpack("<I", planned[IDS["DATSZ_JPGSCN_1_1_TGT"]])[0] == 853


from a7r.formats import plan_xpan, xpan_height


@pytest.mark.parametrize("w, h", [(7360, 2720), (4800, 1776), (3680, 1360), (2400, 880)])
def test_xpan_height_is_65_24_rounded_to_multiple_of_16(w, h):
    assert xpan_height(w) == h


def test_plan_xpan_replaces_16_9_geometry():
    planned = plan_xpan(camera_like_backup())
    assert len(planned) == 42
    assert decode_pxsz(planned[IDS["PXSZ_STL_L_16_9"]]) == (7360, 2720)
    assert decode_pxsz(planned[IDS["PXSZ_STL_M_16_9"]]) == (4800, 1776)
    assert decode_pxsz(planned[IDS["PXSZ_APSC_STL_S_16_9"]]) == (2400, 880)
    names = {v: k for k, v in IDS.items()}
    assert all("_16_9" in names[pid] for pid in planned)


def test_plan_xpan_scales_jpeg_estimates_from_3_2():
    planned = plan_xpan(camera_like_backup())
    got = struct.unpack("<I", planned[IDS["DATSZ_JPG_L_16_9_FINE_MAX"]])[0]
    assert got == math.ceil(2107 * 7360 * 2720 / (7360 * 4912))
