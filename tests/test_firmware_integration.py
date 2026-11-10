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


LIBOBJ = ROOT / "0700_part_image" / "dev" / "nflasha15_unpacked_unpacked" / "lib" / "libObj.so"


@pytest.mark.parametrize("name", ["libobj-image-size-aspect-fallback", "libobj-aspect-menu-unlock"])
def test_libobj_patches_apply_to_stock_3_20(name):
    from a7r.patch import apply_patch
    from a7r.patches import PATCHES
    p = PATCHES[name]
    raw = LIBOBJ.read_bytes()
    out = apply_patch(p, raw)
    assert sum(a != b for a, b in zip(raw, out)) <= 2


def test_cautionconfig_patch_applies_to_stock_3_20():
    from a7r.patch import apply_patch
    from a7r.patches import PATCHES
    lib = ROOT / "0700_part_image" / "dev" / "nflasha15_unpacked_unpacked" / "lib" / "CautionConfig.so"
    raw = lib.read_bytes()
    out = apply_patch(PATCHES["cautionconfig-aspect-menu-full-list"], raw)
    assert sum(a != b for a, b in zip(raw, out)) == 1


def _one_to_one_geometry_ids():
    from a7r.ids import IDS
    return [pid for name, pid in IDS.items() if name.startswith(("DATSZ", "PXSZ")) and "_1_1" in name]


def test_one_to_one_geometry_is_unprotected_and_empty_in_every_template():
    ids = _one_to_one_geometry_ids()
    assert len(ids) == 44
    for f in sorted(TEMPLATES.glob("*.bin")):
        props = BackupFile(f.read_bytes()).properties
        assert {props[pid].attr for pid in ids} == {0}, f.name
        assert all(props[pid].data == bytes(len(props[pid].data)) for pid in ids), f.name
        assert (props[0x01070012].attr, props[0x01070012].data) == (0x60, b"\x01"), f.name


def test_any_update_resets_the_one_to_one_geometry_but_keeps_the_aspect_with_r():
    from a7r import firmup
    from a7r.formats import plan_square
    bk = template()
    old = {pid: p.data for pid, p in bk.properties.items()}
    old.update(plan_square(bk))
    old[0x01070012] = b"\x03"
    ids = _one_to_one_geometry_ids()
    for option in ("w", "u", "r"):
        after = firmup.merge(old, bk.properties, firmup.MODES[option])
        assert all(after[pid] == bk.properties[pid].data for pid in ids), option
    assert firmup.merge(old, bk.properties, firmup.MODES["r"])[0x01070012] == b"\x03"
    assert firmup.merge(old, bk.properties, firmup.MODES["u"])[0x01070012] == b"\x01"
