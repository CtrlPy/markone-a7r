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

# The menu actually runs from libObj.so, which embeds its own copy of
# CmnViewProcessDataElementCustomImageSize (cmn_view_processDataMgr.so is not
# loaded by the camera; checked on device 2026-11-09). Same function
# (Ghidra FUN_0091f9c0, ELF vaddr 0x90f9c0), same four bytes; text segment
# offset == vaddr.
LIBOBJ_IMAGE_SIZE_ASPECT_FALLBACK = BytePatch(
    name="libobj-image-size-aspect-fallback",
    file="libObj.so",
    sha256="11311207320721b2dbf11497ea8e7a7d9ca8f96e64e6157b63ce2fb2b0a48bf3",
    edits=[(0x90FA12, bytes.fromhex("032c00d9"), bytes.fromhex("022c00d0"))],
)

# Aspect Ratio menu gate: libObj's copy of
# CmnViewProcessDataElementCustomImageAspectRatio::isValueGrayedOut(v) (file/vaddr
# 0x903b58, byte-identical to cmn_view_processDataMgr.so 0x60c6c) asks
# WrapperSettingUtil::isInhOn() with inhibit ids 0x96 (4:3), 0x94 (3:2),
# 0x95 (16:9), 0x414 (1:1) and greys the item out when it is on. Replace
# `subs r4, r0, #0` (result = inhibit state) with `movs r4, #0` (result = not
# greyed); the following `it ne; movne r4, #1` then never fires. Values > 3
# stay greyed.
LIBOBJ_ASPECT_MENU_UNLOCK = BytePatch(
    name="libobj-aspect-menu-unlock",
    file="libObj.so",
    sha256="11311207320721b2dbf11497ea8e7a7d9ca8f96e64e6157b63ce2fb2b0a48bf3",
    edits=[(0x903B98, bytes.fromhex("041e"), bytes.fromhex("0024"))],
)

PATCHES = {p.name: p for p in (IMAGE_SIZE_ASPECT_FALLBACK, LIBOBJ_IMAGE_SIZE_ASPECT_FALLBACK,
                                LIBOBJ_ASPECT_MENU_UNLOCK)}
