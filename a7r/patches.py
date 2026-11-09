"""Patch descriptions for ILCE-7R firmware 3.20 (our own work, no Sony code)."""
from a7r.patch import BytePatch

# CmnViewProcessDataElementCustomImageSize::getAspectRatio() ends with
#     cmp r4, #3 ; bls keep ; movs r4, #1      (accept setting 0..3, else 3:2)
# The Image Size menu only has tables for setting 1 (3:2) and 2 (16:9), so for
# 1:1 / 4:3 it found no size at all. Patched to
#     cmp r4, #2 ; beq keep ; movs r4, #1      (16:9 stays 16:9, all else 3:2)
# so the Image Size menu offers the 3:2 L/M/S list in 1:1 and 4:3; the pixel
# geometry still comes from the aspect's own PXSZ values. Function is only
# used inside this library (isValueGrayedOut, isValueDisable,
# convertInternalIdToValue, getValue).
IMAGE_SIZE_ASPECT_FALLBACK = BytePatch(
    name="image-size-aspect-fallback",
    file="cmn_view_processDataMgr.so",
    sha256="c0b710715043ab88ff834740dcbfeb7d9765bb2e705380d878f79c2709c952aa",
    edits=[(0x61ACE, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))],
)

PATCHES = {p.name: p for p in (IMAGE_SIZE_ASPECT_FALLBACK,)}
