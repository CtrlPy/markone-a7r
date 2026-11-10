"""Static layout of the MPR still-size tables in ILCE-7R 3.20 (libmprctrl.so, libmpr.so).

These are the tables the shot counter reads at runtime. See
docs/findings/aspect-ratio.md section 10.
"""
from pathlib import Path

import pytest

from a7r import mprtable

LIB = (Path(__file__).resolve().parent.parent / "fw" / "out" / "firmware.tar_unpacked"
       / "0700_part_image" / "dev" / "nflasha15_unpacked_unpacked" / "lib")
MPRCTRL = LIB / "libmprctrl.so"
LIBMPR = LIB / "libmpr.so"

@pytest.mark.parametrize("size,aspect,quality,index", [
    ("L", "1:1", "STD", 0),
    ("L", "1:1", "EXFINE", 2),
    ("L", "3:2", "STD", 9),
    ("M", "1:1", "FINE", 16),
    ("S", "3:2", "EXFINE", 41),
    ("VGA", "4:3", "EXFINE", 59),
])
def test_jpeg_index_matches_create_still_data_order(size, aspect, quality, index):
    assert mprtable.jpeg_index(size, aspect, quality) == index


def test_jpeg_index_rejects_unknown_values():
    with pytest.raises(ValueError):
        mprtable.jpeg_index("XL", "3:2", "STD")


def test_aspect_indices_cover_every_size_and_quality():
    assert mprtable.aspect_indices("1:1") == [0, 1, 2, 15, 16, 17, 30, 31, 32, 45, 46, 47]
    assert mprtable.aspect_indices("3:2", sizes=("L",)) == [9, 10, 11]


@pytest.mark.firmware
@pytest.mark.skipif(not MPRCTRL.is_file(), reason="firmware not unpacked in fw/out")
def test_still_mgr_global_is_exported_at_known_address():
    elf = mprtable.Elf(MPRCTRL)
    assert elf.symbol("_ZN7MprCtrl11mp_stillMgrE") == mprtable.MPRCTRL_MP_STILLMGR


@pytest.mark.firmware
@pytest.mark.skipif(not MPRCTRL.is_file(), reason="firmware not unpacked in fw/out")
def test_still_size_info_record_for_full_frame_jpeg_points_at_the_60_entry_table():
    elf = mprtable.Elf(MPRCTRL)
    rec = mprtable.StillSizeInfo.read(elf, mprtable.MPRCTRL_SSI_JPEG_FF_RECORD)
    assert (rec.key, rec.table, rec.count) == (0, mprtable.MPRCTRL_JPEG_FF_TABLE, 60)


@pytest.mark.firmware
@pytest.mark.skipif(not MPRCTRL.is_file(), reason="firmware not unpacked in fw/out")
def test_jpeg_table_entries_name_their_backup_estimates():
    """CreateStillData walks a {tgt_id, name, max_id, name} list in the same order as the table."""
    from a7r.bkid import elf_load_segments, find_name_id_pairs
    elf = mprtable.Elf(MPRCTRL)
    ids = mprtable.jpeg_estimate_ids(elf)
    names = find_name_id_pairs(elf.raw, elf_load_segments(MPRCTRL), 403)
    assert len(ids) == 60
    for size in mprtable.SIZES:
        for aspect in mprtable.TABLE_ASPECTS:
            for quality in mprtable.QUALITIES:
                stem = f"BKID_IMAGING_DATSZ_JPG_{size}_{aspect.replace(':', '_')}_{quality}"
                assert ids[mprtable.jpeg_index(size, aspect, quality)] == (names[stem + "_TGT"], names[stem + "_MAX"])


@pytest.mark.firmware
@pytest.mark.skipif(not MPRCTRL.is_file(), reason="firmware not unpacked in fw/out")
@pytest.mark.parametrize("size", mprtable.SIZES)
@pytest.mark.parametrize("aspect", mprtable.DEFSTRUCT_ASPECTS)
def test_get_still_rec_info_routes_every_aspect_to_its_jpeg_slot(size, aspect):
    """GetStillRecInfo (.rodata, StillType 0): {key, index} by size*30 + aspect*6 + crop*3 + quality.

    The input aspect is in DefStruct order (0=3:2 .. 4=17:9); full frame goes to key 0,
    APS-C to key 11, and the index lands on the slot named for the same aspect.
    """
    elf = mprtable.Elf(MPRCTRL)
    for crop, key in ((0, 0), (1, 11)):
        for q, quality in enumerate(mprtable.QUALITIES):
            i = mprtable.SIZES.index(size) * 30 + mprtable.DEFSTRUCT_ASPECTS.index(aspect) * 6 + crop * 3 + q
            entry = mprtable.MPRCTRL_RECINFO_STILL + 8 * i
            assert (elf.u32(entry), elf.u32(entry + 4)) == (key, mprtable.jpeg_index(size, aspect, quality))


@pytest.mark.firmware
@pytest.mark.skipif(not LIBMPR.is_file(), reason="firmware not unpacked in fw/out")
def test_libmpr_keeps_a_pointer_to_the_table_not_a_copy():
    """SetCreateParam_StillSizeInfo stores (ptr, num) in two .bss words that the remain code reads."""
    elf = mprtable.Elf(LIBMPR)
    assert elf.relative_target(mprtable.LIBMPR_GOT_SSI_PTR) == mprtable.LIBMPR_SSI_PTR
    assert elf.relative_target(mprtable.LIBMPR_GOT_SSI_NUM) == mprtable.LIBMPR_SSI_NUM


# --- per-shot estimate formula (MprCtrlStillMgr::CalcStillData_JPG) ---

def test_estimate_adds_header_screennail_and_page_padding_for_large_images():
    # 1001 KiB = 1025024 bytes, padded to 4096 -> +3072
    target, maximum = mprtable.jpeg_estimate(
        tgt_kib=1001, max_kib=2000, hdr_kib=20, scn_tgt_kib=300, scn_max_kib=400,
        x40_kib=3, x44_kib=40, area=4_000_000)
    assert target == 1025024 + 20480 + 307200 + 3072 + 40960 + 3072
    assert maximum == 2048000 + 20480 + 409600 + 3072 + 40960 + 0


def test_estimate_skips_screennail_and_padding_at_or_below_the_area_threshold():
    target, maximum = mprtable.jpeg_estimate(
        tgt_kib=1001, max_kib=2000, hdr_kib=20, scn_tgt_kib=300, scn_max_kib=400,
        x40_kib=3, x44_kib=40, area=3_999_999)
    assert target == 1025024 + 20480 + 3072 + 40960
    assert maximum == 2048000 + 20480 + 3072 + 40960


def test_estimate_is_zero_when_the_backup_value_is_zero():
    """This is what leaves the hidden aspects at {0, 0}: empty DATSZ slots at init."""
    assert mprtable.jpeg_estimate(0, 0, 20, 300, 400, 3, 40, 24_000_000) == (0, 0)
    assert mprtable.jpeg_estimate(0, 2000, 20, 300, 400, 3, 40, 24_000_000)[0] == 0


@pytest.mark.firmware
@pytest.mark.skipif(not MPRCTRL.is_file(), reason="firmware not unpacked in fw/out")
def test_formula_constants_are_the_literals_calc_still_data_jpg_loads():
    elf = mprtable.Elf(MPRCTRL)
    assert elf.u32(0x16148) == mprtable.HDR_ID
    assert elf.u32(0x1614C) == mprtable.X40_ID
    assert elf.u32(0x16150) == mprtable.X44_ID
    assert elf.u32(0x157A0) == mprtable.SCN_AREA_THRESHOLD


@pytest.mark.firmware
@pytest.mark.skipif(not MPRCTRL.is_file(), reason="firmware not unpacked in fw/out")
def test_pixel_size_and_screennail_id_tables_follow_the_table_aspect_order():
    from a7r.bkid import elf_load_segments, find_name_id_pairs
    elf = mprtable.Elf(MPRCTRL)
    names = find_name_id_pairs(elf.raw, elf_load_segments(MPRCTRL), 403)
    pxsz, scn = mprtable.pxsz_ids(elf), mprtable.scn_ids(elf)
    for s, size in enumerate(mprtable.SIZES):
        for a, aspect in enumerate(mprtable.TABLE_ASPECTS):
            assert pxsz[s * 5 + a] == names[f"BKID_IMAGING_PXSZ_STL_{size}_{aspect.replace(':', '_')}"]
    for a, aspect in enumerate(mprtable.TABLE_ASPECTS):
        stem = f"BKID_IMAGING_DATSZ_JPGSCN_{aspect.replace(':', '_')}"
        assert scn[a] == (names[stem + "_TGT"], names[stem + "_MAX"])


@pytest.mark.firmware
@pytest.mark.skipif(not MPRCTRL.is_file(), reason="firmware not unpacked in fw/out")
def test_expected_estimates_from_the_factory_template():
    """3:2 and 16:9 get real sizes; the hidden 1:1 slots come out as {0, 0}."""
    from a7r.backup import BackupFile
    template = MPRCTRL.parents[4] / "0110_backup" / "SYSMUSASHI-DSLR" / "ICH_UUG" / "CX77900_UC2.bin"
    props = {pid: p.data for pid, p in BackupFile(template.read_bytes()).properties.items()}
    est = mprtable.expected_jpeg_estimates(props, mprtable.Elf(MPRCTRL))
    assert len(est) == 60
    assert est[mprtable.jpeg_index("L", "3:2", "FINE")] == (12603392, 19609600)
    assert est[mprtable.jpeg_index("L", "16:9", "STD")] == (7524352, 11540480)
    assert all(est[i] == (0, 0) for i in mprtable.aspect_indices("1:1"))
