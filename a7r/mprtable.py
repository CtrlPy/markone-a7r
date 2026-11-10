"""Static layout of the MPR still-size tables (ILCE-7R 3.20).

The shot counter ("remaining shots") is computed by libmpr.so inside the main
camera process (im.elf). Per-shot file size estimates come from tables that
libmprctrl.so builds once, in MprCtrl::Init:

  MprCtrl::mp_stillMgr -> MprCtrlStillMgr
      +4  _StillSizeTable (heap, 99 rows x 8 bytes: Backup PXSZ copies)
      +8  StillSizeInfo[21] (bss 0x3cd04, copied from .data.rel.ro records)
      +12 21

  StillSizeInfo = {u32 key, u32 unit, u32 *table, u32 count, u32 extra}
  key 0 (full-frame JPEG): table = .data 0x3bbfc, 60 x {u32 n=1, u32 *est}
      est (heap, 8 bytes) = {target, max}, computed by CalcStillData_JPG from
      the Backup DATSZ/JPGSCN values *at init time*.

  index = size * 15 + table_aspect * 3 + quality
      sizes L, M, S, VGA; table aspects 1:1, 16:9, 17:9, 3:2, 4:3 (the order
      of the BKID names); qualities STD, FINE, EXFINE.

libmpr.so keeps only a pointer to StillSizeInfo (MprIf::SetCreateParam_StillSizeInfo
stores ptr/num in .bss) and dereferences the estimate pointers on every remain
calculation, so the values in the heap blocks are what the counter uses.
Addresses are ELF virtual addresses of the stock 3.20 files.
"""
import struct
from dataclasses import dataclass
from pathlib import Path

SIZES = ("L", "M", "S", "VGA")
TABLE_ASPECTS = ("1:1", "16:9", "17:9", "3:2", "4:3")
DEFSTRUCT_ASPECTS = ("3:2", "4:3", "16:9", "1:1", "17:9")
QUALITIES = ("STD", "FINE", "EXFINE")

# libmprctrl.so
MPRCTRL_MP_STILLMGR = 0x3CCC8          # MprCtrl::mp_stillMgr (MprCtrlStillMgr *)
MPRCTRL_SSI_TABLE = 0x3CD04            # StillSizeInfo[21] handed to MPR
MPRCTRL_SSI_COUNT = 21
MPRCTRL_SSI_JPEG_FF_RECORD = 0x3A3C4   # .data.rel.ro template record for key 0
MPRCTRL_JPEG_FF_TABLE = 0x3BBFC        # 60 x {n, *estimate}
MPRCTRL_JPEG_FF_IDS = 0x398E8          # 60 x {tgt_id, *name, max_id, *name}
MPRCTRL_RECINFO_STILL = 0x2C648        # GetStillRecInfo StillType 0 routing, 120 x {key, index}
MPRCTRL_PXSZ_IDS = 0x39CA8             # 20 x {pxsz_id, *name}: rows of _StillSizeTable, size*5 + aspect
MPRCTRL_SCN_IDS = 0x3A280              # 5 x {scn_tgt_id, *name, scn_max_id, *name}, by table aspect
STILL_SIZE_TABLE_BYTES = 0x318         # _StillSizeTable: 99 rows x {u16 w, u16 h, u32 w*h}

# Backup.bin ids and the limit that MprCtrlStillMgr::CalcStillData_JPG uses for every JPEG mode
HDR_ID = 0x0005007B                    # u32, KiB
X40_ID = 0x003C037A                    # u16, KiB
X44_ID = 0x00050095                    # read as u16, KiB
SCN_AREA_THRESHOLD = 3_999_999         # screennail + 4 KiB padding only above this pixel count

# libmpr.so
LIBMPR_GOT_SSI_PTR = 0x7CB04C
LIBMPR_GOT_SSI_NUM = 0x7CCA4C
LIBMPR_SSI_PTR = 0x8565F8
LIBMPR_SSI_NUM = 0x856604

R_ARM_RELATIVE = 23


def jpeg_index(size: str, aspect: str, quality: str) -> int:
    """Index into the 60-entry JPEG estimate table; aspect as '1:1', '3:2', ..."""
    return SIZES.index(size) * 15 + TABLE_ASPECTS.index(aspect) * 3 + QUALITIES.index(quality)


def aspect_indices(aspect: str, sizes=SIZES) -> list[int]:
    return [jpeg_index(s, aspect, q) for s in sizes for q in QUALITIES]


class Elf:
    """Minimal reader for 32-bit little-endian ARM shared objects."""

    def __init__(self, path):
        from elftools.elf.elffile import ELFFile
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        with open(self.path, "rb") as f:
            elf = ELFFile(f)
            self.segments = [(s["p_offset"], s["p_vaddr"], s["p_filesz"])
                             for s in elf.iter_segments() if s["p_type"] == "PT_LOAD"]
            self.symbols = {s.name: s["st_value"] for s in elf.get_section_by_name(".dynsym").iter_symbols()}
            self.relocs = {}
            for sec in elf.iter_sections():
                if sec.name.startswith(".rel"):
                    for r in sec.iter_relocations():
                        self.relocs[r["r_offset"]] = (r["r_info_type"], r["r_info_sym"])

    def offset(self, vaddr: int) -> int:
        for off, va, size in self.segments:
            if va <= vaddr < va + size:
                return off + vaddr - va
        raise ValueError(f"{vaddr:#x} is not file-backed in {self.path.name}")

    def u32(self, vaddr: int) -> int:
        return struct.unpack_from("<I", self.raw, self.offset(vaddr))[0]

    def symbol(self, name: str) -> int:
        return self.symbols[name]

    def relative_target(self, vaddr: int) -> int:
        """Address a word resolves to at load time, for an R_ARM_RELATIVE slot."""
        rtype, _ = self.relocs[vaddr]
        if rtype != R_ARM_RELATIVE:
            raise ValueError(f"{vaddr:#x} has relocation type {rtype}, not R_ARM_RELATIVE")
        return self.u32(vaddr)


@dataclass(frozen=True)
class StillSizeInfo:
    key: int
    unit: int
    table: int
    count: int
    extra: int

    SIZE = 0x14

    @classmethod
    def read(cls, elf: Elf, vaddr: int) -> "StillSizeInfo":
        words = [elf.u32(vaddr + 4 * i) for i in range(5)]
        return cls(*words)

    @classmethod
    def unpack(cls, data: bytes) -> "StillSizeInfo":
        return cls(*struct.unpack_from("<5I", data))


def jpeg_estimate_ids(elf: Elf) -> list[tuple[int, int]]:
    """(target_id, max_id) Backup.bin ids per JPEG table index, as CreateStillData reads them."""
    out = []
    for i in range(60):
        base = MPRCTRL_JPEG_FF_IDS + 16 * i
        out.append((elf.u32(base), elf.u32(base + 8)))
    return out


def pxsz_ids(elf: Elf) -> list[int]:
    """PXSZ Backup.bin ids of the first 20 _StillSizeTable rows (full-frame stills)."""
    return [elf.u32(MPRCTRL_PXSZ_IDS + 8 * i) for i in range(20)]


def scn_ids(elf: Elf) -> list[tuple[int, int]]:
    """(target_id, max_id) of the screennail estimate per table aspect."""
    return [(elf.u32(MPRCTRL_SCN_IDS + 16 * a), elf.u32(MPRCTRL_SCN_IDS + 16 * a + 8)) for a in range(5)]


def jpeg_estimate(tgt_kib, max_kib, hdr_kib, scn_tgt_kib, scn_max_kib, x40_kib, x44_kib, area):
    """{target, max} bytes per shot, as MprCtrlStillMgr::CalcStillData_JPG computes them.

    All inputs are Backup.bin values in KiB; area is the pixel count of the mode.
    A zero DATSZ value gives a zero estimate, whatever the other terms are.
    """
    target, maximum = tgt_kib << 10, max_kib << 10
    fixed = (hdr_kib << 10) + (x40_kib << 10) + (x44_kib << 10)
    scn_target = scn_max = pad_target = pad_max = 0
    if area > SCN_AREA_THRESHOLD:
        scn_target, scn_max = scn_tgt_kib << 10, scn_max_kib << 10
        pad_target, pad_max = -target % 4096, -maximum % 4096
    return (target + fixed + scn_target + pad_target if target else 0,
            maximum + fixed + scn_max + pad_max if maximum else 0)


def expected_jpeg_estimates(props, elf: Elf) -> list[tuple[int, int]]:
    """What MprCtrl::Init would put into the 60 full-frame JPEG blocks for these settings.

    props maps Backup.bin property id -> raw bytes (e.g. from a7r.backup.BackupFile).
    """
    def value(pid, size=4):
        return int.from_bytes(props[pid][:size], "little")

    hdr, x40, x44 = value(HDR_ID), value(X40_ID, 2), value(X44_ID, 2)
    ids, pxsz, scn = jpeg_estimate_ids(elf), pxsz_ids(elf), scn_ids(elf)
    out = []
    for i, (tgt_id, max_id) in enumerate(ids):
        size, aspect = i // 15, i % 15 // 3
        area = struct.unpack_from("<HHI", props[pxsz[size * 5 + aspect]])[2]
        scn_tgt_id, scn_max_id = scn[aspect]
        out.append(jpeg_estimate(value(tgt_id), value(max_id), hdr, value(scn_tgt_id), value(scn_max_id),
                                 x40, x44, area))
    return out
