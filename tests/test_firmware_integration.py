"""Checks against a locally unpacked ILCE-7R 3.20 firmware (see README)."""
import struct
from pathlib import Path

import pytest

from a7r.backup import BackupFile
from a7r.bkid import elf_load_segments, find_name_id_pairs

ROOT = Path(__file__).resolve().parent.parent / "fw" / "out" / "firmware.tar_unpacked"
TEMPLATES = ROOT / "0110_backup" / "SYSMUSASHI-DSLR" / "ICH_UUG"
MPRCTRL = ROOT / "0700_part_image" / "dev" / "nflasha15_unpacked_unpacked" / "lib" / "libmprctrl.so"

pytestmark = [
    pytest.mark.firmware,
    pytest.mark.skipif(not TEMPLATES.is_dir(), reason="firmware not unpacked in fw/out"),
]


def template(name="CX77900_UC2.bin"):
    return BackupFile((TEMPLATES / name).read_bytes())


def test_all_region_templates_parse_with_same_layout():
    files = sorted(TEMPLATES.glob("*.bin"))
    assert len(files) == 11
    layouts = {(b.num_subsystems, len(b.properties)) for b in map(lambda f: BackupFile(f.read_bytes()), files)}
    assert layouts == {(403, 15868)}


def test_template_holds_model_name():
    assert template().properties[0x003E0005].data.rstrip(b"\0") == b"ILCE-7R"


def test_libmprctrl_bkid_table_resolves_to_template_ids():
    bk = template()
    pairs = find_name_id_pairs(MPRCTRL.read_bytes(), elf_load_segments(MPRCTRL), bk.num_subsystems)
    resolved = [n for n, pid in pairs.items() if pid in bk.properties]
    assert len(pairs) == 711
    assert len(resolved) == 710
    assert pairs["BKID_IMAGING_DATSZ_JPG_L_3_2_FINE_MAX"] == 0x00050014


def test_hidden_aspect_jpeg_size_estimates_are_zero_on_a7r():
    bk = template()
    pairs = find_name_id_pairs(MPRCTRL.read_bytes(), elf_load_segments(MPRCTRL), bk.num_subsystems)
    value = lambda n: int.from_bytes(bk.properties[pairs[n]].data, "little")
    assert value("BKID_IMAGING_DATSZ_JPG_L_3_2_FINE_TGT") > 0
    assert value("BKID_IMAGING_DATSZ_JPG_L_4_3_FINE_TGT") == 0
    assert value("BKID_IMAGING_DATSZ_JPG_L_1_1_FINE_TGT") == 0


@pytest.mark.parametrize("size", ["L", "M", "S"])
@pytest.mark.parametrize("aspect", ["3_2", "16_9"])
def test_jpeg_size_estimates_are_physically_consistent(size, aspect):
    """MAX >= TGT and EXFINE > FINE > STD, which only holds with the right table layout."""
    bk = template()
    pairs = find_name_id_pairs(MPRCTRL.read_bytes(), elf_load_segments(MPRCTRL), bk.num_subsystems)
    v = {}
    for q in ("STD", "FINE", "EXFINE"):
        for kind in ("TGT", "MAX"):
            pid = pairs[f"BKID_IMAGING_DATSZ_JPG_{size}_{aspect}_{q}_{kind}"]
            v[q, kind] = int.from_bytes(bk.properties[pid].data, "little")
        assert v[q, "MAX"] >= v[q, "TGT"] > 0
    assert v["EXFINE", "TGT"] > v["FINE", "TGT"] > v["STD", "TGT"]


def pixel_size(bk, pairs, name):
    w, h, n = struct.unpack("<HHI", bk.properties[pairs[name]].data)
    return w, h, n


def test_still_pixel_sizes_match_a7r_spec_and_hidden_aspects_are_empty():
    bk = template()
    pairs = find_name_id_pairs(MPRCTRL.read_bytes(), elf_load_segments(MPRCTRL), bk.num_subsystems)
    assert pixel_size(bk, pairs, "BKID_IMAGING_PXSZ_STL_L_3_2") == (7360, 4912, 7360 * 4912)
    assert pixel_size(bk, pairs, "BKID_IMAGING_PXSZ_STL_L_16_9") == (7360, 4144, 7360 * 4144)
    assert pixel_size(bk, pairs, "BKID_IMAGING_PXSZ_STL_M_3_2") == (4800, 3200, 4800 * 3200)
    for hidden in ("1_1", "4_3"):
        for size in ("L", "M", "S"):
            assert pixel_size(bk, pairs, f"BKID_IMAGING_PXSZ_STL_{size}_{hidden}") == (0, 0, 0)


def test_geometry_id_table_matches_libmprctrl():
    from a7r.ids import IDS
    bk = template()
    pairs = find_name_id_pairs(MPRCTRL.read_bytes(), elf_load_segments(MPRCTRL), bk.num_subsystems)
    inferred = {"DATSZ_APSC_JPG_S_3_2_EXFINE_TGT"}
    for name, pid in IDS.items():
        if name in inferred:
            assert pid in bk.properties
            continue
        assert pairs["BKID_IMAGING_" + name] == pid, name
