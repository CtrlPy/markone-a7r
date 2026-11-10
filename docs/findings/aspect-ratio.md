# Aspect ratio findings (ILCE-7R 3.20)

Static findings come from the official 3.20 updater, unpacked locally (see
README). Camera results come from one ILCE-7R on firmware 3.20 (from
2026-11-09). Reproduce with the commands under each section; the experiment
history is in [../LOG.md](../LOG.md).

## Current state (2026-11-10)

| Item | Status | Evidence |
| --- | --- | --- |
| Aspect setting `0x01070012`: 1 = 3:2, 2 = 16:9, 3 = 1:1, 0 = 4:3 | Confirmed (camera) | §5 |
| Square live view on LCD and EVF with value 3 | Confirmed (camera) | §5 |
| 1:1 PXSZ / DATSZ / JPGSCN values written to Backup.bin | Done (camera) | §6, LOG |
| Image Size menu in 1:1 after the libObj RAM patch | Confirmed (camera) | §7 |
| PXSZ is the encoder output size, not the crop window | Confirmed (camera) | §8 |
| Aspect Ratio item list is fixed by the node constructor at init | Confirmed (static + camera) | §9 |
| Camera resumes from a flash snapshot, even after a battery pull | Confirmed (camera: dmesg `WARMBOOT`, `/proc/ssboot`) | LOG |
| Shot counter reads per-shot JPEG estimates that libmprctrl computes once at init and libmpr dereferences at runtime | Confirmed (static) | §10 |
| No stock code path rebuilds those estimates after init | Confirmed (static: `MprCtrl::Init` runs once, no `Term`) | §10 |
| The 1:1 estimate blocks in RAM are zero, and that is why the counter is 0 | Confirmed (camera, read-back + fill) | §10, §11 |
| **With the nine 1:1 blocks filled in RAM the camera shoots 1:1**: counter shown, 4912×4912 / 2448×2448 JPEG, true sensor crop | Confirmed (camera, 2026-11-10) | §11 |
| Image Size menu in 1:1 with the libObj patch applied without the terminal | Confirmed (camera, 2026-11-10) | §11 |
| Closing Sony's service terminal crashes the kernel in about half of the sessions; terminal-free sessions of ≥ 3 s do not | Confirmed (camera, `/proc/klog`, laptop USB log, two days) | §12 |
| Shutter-dial overlay does not update while turning in 1:1 (the value is applied) | Open, separate UI issue | §11 |
| Aspect Ratio menu still lists only 3:2 and 16:9 | Open (list fixed at init, §9) | §9 |
| RAW and RAW+JPEG in 1:1 | Not tested | — |
| What decides the sensor crop window per aspect (needed for a true XPan crop) | Open | §8 |

## 1. The factory Backup.bin templates are in the firmware

`0110_backup/SYSMUSASHI-DSLR/ICH_UUG/` holds 11 factory `Backup.bin` images, one
per region (`CX77900_*`, `CX77901_*`). All are BK4, 403 subsystems,
15 868 properties, version string `34134_12.2016052801`. Known ids from
Sony-PMCA-RE check out (`0x003e0005` = `ILCE-7R`, `0x01660024` = `2.3`).

Regions differ in 47 properties (languages, PAL/NTSC, region strings), none of
them aspect related.

```
python -m a7r.backup dump  fw/out/.../ICH_UUG/CX77900_UC2.bin | head
python -m a7r.backup diff  fw/out/.../ICH_UUG/CX77900_UC2.bin fw/out/.../ICH_UUG/CX77901_CE.bin
```

## 2. libmprctrl.so names 711 Backup.bin ids

`lib/libmprctrl.so` carries a table of `{u32 id; const char *name;}` entries
for `BKID_IMAGING_*` properties (subsystem `0x0005`). 710 of 711 names resolve
to properties present in the factory template.

The `{id, name}` order is confirmed by the data: read the other way round only
697 resolve and the JPEG size estimates contradict themselves (MAX < TGT).

```
python -m a7r.bkid fw/out/.../lib/libmprctrl.so fw/out/.../ICH_UUG/CX77900_UC2.bin --grep PXSZ_STL
```

## 3. Still image geometry per aspect lives in Backup.bin, and 1:1 / 4:3 are empty

`BKID_IMAGING_PXSZ_*` values are `u16 width, u16 height, u32 width*height`.
Full-frame stills (`STL`) in the UC2 template:

| Size | 3:2 | 16:9 | 4:3 | 1:1 | 17:9 |
| --- | --- | --- | --- | --- | --- |
| L | 7360×4912 (`0x000502bc`) | 7360×4144 (`0x000502ba`) | 0 (`0x000502bd`) | 0 (`0x000502b9`) | 0 (`0x000502bb`) |
| M | 4800×3200 (`0x000502c1`) | 4800×2704 (`0x000502bf`) | 0 (`0x000502c2`) | 0 (`0x000502be`) | 0 (`0x000502c0`) |
| S | 3680×2456 (`0x000502c6`) | 3680×2072 (`0x000502c4`) | 0 (`0x000502c7`) | 0 (`0x000502c3`) | 0 (`0x000502c5`) |

The APS-C crop set (`APSC_STL_*`, `0x0005028c`–`0x0005029f`) follows the same
pattern: 3:2 and 16:9 filled, 1:1 / 4:3 / 17:9 zero.

JPEG size estimates (`BKID_IMAGING_DATSZ_JPG_{L,M,S}_{aspect}_{STD,FINE,EXFINE}_{TGT,MAX}`,
probably KiB) are filled for 3:2 and 16:9 and zero for 1:1, 4:3 and 17:9. Example L 3:2:
STD 7 433 / 11 893, FINE 11 389 / 17 916, EXFINE 22 778 / 36 348 (TGT / MAX).

**Meaning.** The imaging pipeline takes its output geometry and buffer
estimates from these properties. On A7R the slots for the hidden aspects exist
but were never filled. Selecting a hidden aspect without filling them would
most likely give a 0×0 image size or a zero shot counter.

## 4. The pipeline and the GUI both enumerate more than two aspects

- `libmprctrl.so` debug help: `[Aspect]:0(3:2)/1(4:3)/2(16:9)` for stills.
- `wrapperImageAspect.so`, `WrapperImageAspect::convertValueToProcessValueId`:
  GUI enum 1→3, 2→0, 3→2, 4→1. With the pipeline values above, 3 is most
  likely 1:1, so the GUI wrapper knows four aspects: 1:1, 3:2, 16:9, 4:3.
- `cmn_view_processDataMgr.so`, `CmnViewProcessDataElementCustomImageAspectRatio::isValueGrayedOut(v)`:
  for v = 0..3 it checks inhibit ids `0x96`, `0x94`, `0x95`, `0x414`. That is the
  per-value menu gate. Where the inhibit table comes from (code or data) is open.
- `libScalarDaemon.so` (Remote / Web API) has
  `MSG_PARAM_ID_CAMERA_SUPPORTED_PARAMETERS_IMAGE_ASPECT_RATIOS` and
  `PARAMID_CAMSETTING_IMAGE_ASPECT_RATIO`: a route to read the supported list and
  set the value without the menu.

## 5. The user's aspect setting is Backup.bin `0x01070012` (confirmed on camera)

Three Backup.bin reads from a real ILCE-7R (3:2 → 16:9 → 3:2, nothing else
changed) differ in 13 properties; only `0x01070012` follows the menu:

| Value | Meaning |
| --- | --- |
| 1 | 3:2 (factory reset value) |
| 2 | 16:9 |
| 0, 3 | the two hidden aspects, 4:3 and 1:1 in some order |

`CmnViewProcessDataElementCustomImageSize::getAspectRatio()` reads this
property and accepts only values below 4 (anything else falls back to 1). The
menu gate `isValueGrayedOut(v)` uses the same 0..3 domain: v=0 → inhibit `0x96`,
1 → `0x94`, 2 → `0x95`, 3 → `0x414`.

Pipeline enum (`DefStruct::STILL_ASPECT_*` name table order, matches the
`libmprctrl` debug help): 0 = 3:2, 1 = 4:3, 2 = 16:9, 3 = 1:1, 4 = 17:9.
`UtilStillSize::CnvStillAspect(i)` maps i → `[3, 2, 4, 0, 1][i]` (table at
ELF vaddr `0x2eb4c`), a conversion between two internal enums, not from the
setting.

**Confirmed on camera 2026-11-09:** writing 3 gives a square live view on LCD
and EVF with no errors, so 3 = 1:1, and 0 = 4:3 by elimination (0 not tried on
the camera). The menu still lists only 3:2 and 16:9 (see §9).

## 6. Where the settings path stops (camera + decompilation, 2026-11-09)

With `0x01070012 = 3` and all 1:1 PXSZ/DATSZ/JPGSCN values filled:

- Live view is square on LCD and EVF (data driven, works).
- `MprCtrlStillMgr::GetStillDataInfo` picks size-estimate ids from a table
  indexed by `size*30 + aspect*6 + crop*3 + quality` (DefStruct aspect order
  0=3:2, 1=4:3, 2=16:9, 3=1:1, 4=17:9); for 1:1 it reads our filled ids.
- **The Image Size menu has no 1:1 branch in code.**
  `CmnViewProcessDataElementCustomImageSize::convertInternalIdToValue` and
  `isValueDisable` only have tables for setting values 1 (3:2) and 2 (16:9);
  any other aspect returns invalid (0x45). On camera: Image Size is blank and
  not selectable, JPEG shows 0 shots / "no space", RAW and RAW+JPEG hide the
  counter.

Conclusion: the settings-level stage cannot finish 1:1 on its own. The next
step needs a code change (in-memory first, Stage 3) or the app route (Stage 4).

## 7. Stage 3 in RAM: the Image Size menu works in 1:1 (2026-11-09)

- The menu classes run from `libObj.so`, which embeds its own copy of
  `CmnViewProcessDataElementCustomImageSize`; `cmn_view_processDataMgr.so` is
  never loaded (a RAM bind-mount of a patched copy had no effect).
- Patch `libobj-image-size-aspect-fallback`: 4 bytes at libObj file/vaddr
  `0x90fa12` (`cmp r4,#3; bls` → `cmp r4,#2; beq`), so every aspect except
  16:9 uses the 3:2 Image Size list.
- Applied in RAM only, through Sony's own senser MemoryDump at the physical
  address of the page (pagemap PFN), after checking the whole 4 KiB page
  against the file. Running our own static helper binary resets the camera,
  even read-only; built-in tools (busybox dd, MemoryDump) do not.
- Settings can be written through the service channel without a reboot
  (`a7r.stage1 --mode service`), which keeps RAM patches alive.

Result on camera: Image Size is selectable in 1:1 (labels still show the 3:2
megapixels), live view square. **Shot counter stays 0 / "no space"**: the
remain count is computed elsewhere. `MprCtrl::GetStillSizeTable()` lookups
(libObj `FUN_00c2c3f0`, nearest-area fallback `FUN_00c2c214`) do not produce a
zero by themselves; the counter path is still to be found (found later, §10).

## 8. PXSZ is the output size, not the crop (2026-11-09)

Writing XPan 65:24 geometry into the 16:9 slot (PXSZ L 7360x2720 etc.) and
shooting in 16:9 gave a 7360x2720 JPEG, but **vertically squeezed**: object
proportions are 1.52x wider than in the 3:2 reference and the 16:9 screennail
(1920x1080), i.e. 4144/2720. The camera reads the 16:9 window and scales it to
the PXSZ size.

Consequences:
- PXSZ = encoder output size; the sensor crop window comes from the aspect
  setting. Matching both is required for undistorted images.
- 1:1 is consistent already: aspect setting 3 gives a square window (square
  live view) and the 1:1 PXSZ is square.
- XPan needs its own crop window (code or other tables), not just PXSZ.

## 9. The menu lock is a list choice made at init (2026-11-09)

- The Aspect Ratio menu shows a per-model item list. `_getSubNode()` in
  `CautionConfig.so` reads the read-only UI model type (Backup 0x01070316,
  A7R = 27) and, because bit 27 is in mask 0x5ca00002, uses `Type01`
  {3:2, 16:9}. The `Default` list has all four: 3:2, 16:9, 4:3, 1:1.
- Greying (`isValueGrayedOut`, inhibit ids 0x96/0x94/0x95/0x414) is a second,
  separate layer.
- The list is chosen when the node object is constructed: the constructor
  `CmnViewSettingNodeStlImageAspectRatio(...)` calls `_getSubNode()`, which
  stores the list pointer and count in the node (`+4`, `+8`). The tree is
  built once at init and resumed from the flash snapshot (`/wbi`), so the RAM
  patch of the literal in `_getSubNode()` had no effect (camera, 2026-11-09).
  `CmnViewSettingNode::init()` later reads the list only through the virtual
  `getSubNode()`, which returns those two stored members.
- Not tried: changing the two members of the live node object in RAM. Whether
  the menu re-reads them (e.g. through `updateSettingNode()`, which re-runs
  `init()`) is unknown. The menu is not needed to shoot 1:1, because the aspect
  can be set through the service channel.

Superseded (2026-11-10): this section used to conclude that init-time state can
only change through a cold boot with patched files. For the shot counter that
is not so. The counter's tables are plain data in the camera process and can
be changed in RAM (§10).

## 10. The shot counter reads init-time estimates through pointers (static, 2026-11-10)

Where the "remaining shots" number comes from, traced in Ghidra (libmprctrl.so,
libmpr.so) and pinned in `tests/test_mprtable.py` (`a7r/mprtable.py` holds the
addresses):

- `MprCtrl::Init` (libmprctrl) runs once, guarded by `MprCtrl::mb_initFlag`;
  there is no `Term`. It creates `MprCtrl::mp_stillMgr` (ELF `0x3ccc8`), reads
  the Backup.bin geometry (`GetBackupStillSize`, a 99-row PXSZ copy in the
  heap) and builds the estimates (`CreateStillData`).
- `CreateStillData` computes, per JPEG mode, `{target, max}` from the Backup.bin
  DATSZ, screennail and header values (`CalcStillData_JPG`) and stores each
  pair in its own 8-byte heap block. The full-frame JPEG table (`.data`
  `0x3bbfc`) has 60 entries `{1, *block}`, index `size*15 + aspect*3 + quality`
  with sizes L, M, S, VGA, aspects in the order 1:1, 16:9, 17:9, 3:2, 4:3 and
  qualities STD, FINE, EXFINE. The id list it walks names every entry, so the
  order is read from the firmware, not guessed. 1:1 L is index 0..2, 3:2 L
  index 9..11.
- A 21-entry `StillSizeInfo` array (`.bss` `0x3cd04`, `{key, unit, *table,
  count, extra}`; key 0 = full-frame JPEG, key 11 = APS-C JPEG) is handed to
  MPR with `MprIf::SetCreateParam_StillSizeInfo`. libmpr stores only the
  pointer and the count (`.bss` `0x8565f8` / `0x856604`), not a copy.
- On every remain calculation (`MprIf::GetStillContentsRemain` → media
  manager → `FUN_004b5490` in libmpr, Ghidra addresses) libmpr dereferences
  `table[index].block`. The routing from the user's setting to `{key, index}`
  (`MprCtrlStillMgr::GetStillRecInfo`, `.rodata` `0x2c648`) is complete for
  1:1 and sends it to the 1:1 slots.
- Card insertion or removal re-creates the media managers (`CreateMMgr`), but
  they get the same pointer. No stock path recomputes the estimates.

Consequences:
- If the snapshot was taken while the 1:1 DATSZ values were zero (they were,
  in every Sony template), the 1:1 blocks hold `{0, 0}` in RAM no matter what
  Backup.bin says now. A zero per-shot size gives a zero remain count. This
  matches the camera (counter 0, "no space"); **confirmed on 2026-11-10** (§11).
- The blocks are ordinary heap data of `im.elf` and can be changed in RAM with
  Sony's service-mode memory command at the physical address, with no flash
  write and no cold boot. A battery pull resumes from the snapshot and undoes
  it. (Reading them through the service terminal turned out to be unsafe, §12.)

Reproduce:
```
.venv/bin/python -m pytest tests/test_mprtable.py
# Ghidra: tools/ghidra/DecompileRefsTo.java on libmpr.so finds the readers of 0x8665f8 (image base 0x10000)
```

## 11. 1:1 works with RAM-only fixes (camera, 2026-11-10)

Procedure that makes the A7R shoot 1:1 (each step is a terminal-free service
session, §12; all changes except the aspect setting live in RAM only):

1. Backup.bin holds the 1:1 geometry and estimates (§6; done on 2026-11-09
   with `a7r.stage1`) and the aspect setting `0x01070012 = 03`
   (`a7r.stage1 --mode service --set 0x01070012=03`).
2. `a7r.mprphys --fill L:STD ... --fill S:EXFINE` writes the nine 1:1 L/M/S
   estimate blocks with the values `CalcStillData_JPG` gives for the current
   Backup.bin (`a7r.mprtable.expected_jpeg_estimates`). The estimate page is
   at virtual 0x0ac09000 / physical 0x8a4b2000 after every resume from the
   snapshot (block i at +0x138 + 16·i, glibc chunk header 0x15, thread arena).
   Before each 8-byte write the whole page is compared with the formula: every
   non-1:1 block must match exactly (18 of them are non-zero), so a wrong page
   cannot pass.
3. `a7r.codepatch --scan` applies `libobj-image-size-aspect-fallback`. The
   libObj code frame moves between boots (0x88cc2000, 0x88bb7000, 0x88f60000
   seen), so the tool searches ordinary Linux RAM through MemoryDump (about
   8.5 MB/s) for a page equal to the library file apart from the patch site,
   and writes only there.

Result on the camera: square live view on LCD and EVF, 1:1 icon, shot counter
shown, Image Size L/M/S selectable (labels show the 3:2 megapixels), JPEGs of
4912×4912 (L) and 2448×2448 (S), Quality Fine, Sony's maker note
`AspectRatio: 1:1`. Object proportions match the 3:2 reference (pot
width/height ≈ 1.05 vs ≈ 1.10; a squeezed 3:2 frame would give ≈ 0.70): a true
sensor crop.

Persistence: the power switch suspends to RAM and keeps everything. A battery
pull resumes from the snapshot and clears steps 2–3; the aspect setting
(step 1) stays, and the camera then shows a square view with a counter of 0
until steps 2–3 are run again (two short sessions).

Known issue: in 1:1 the on-screen overlay that follows the shutter-speed dial
does not update while turning; the new speed is applied (visible after a
half-press, EXIF shows it). It froze with the Image Size patch on 2026-11-09
too, so it is a separate UI problem.

## 12. The service terminal crashes the kernel; terminal-free sessions do not (2026-11-10)

- Sony-PMCA-RE's service shell opens a USB terminal on the running camera
  (`usbg_sen_ldisc_open`). Within 0.06–3 s after it is closed the kernel often
  oopses (`/proc/klog`: NULL pointer in `free_block` from a kworker, or a call
  through NULL in `hdmi_workqueue`), and Sony's handler resets through the
  watchdog (`kernel BUG at arch/arm/mach-cxd90014/wdt.c:182`). Over two days
  19 of 36 terminal sessions ended that way, independent of the aspect, of
  RAM patches and of what ran in the session; most of these restarts went
  unnoticed on 2026-11-09. Restarts drop every RAM change and roll the
  settings back to the last flash save.
- Service sessions that use only Sony's commands (Backup read/write,
  MemoryDump) have not crashed, provided they stay in service mode for at
  least about 0.7 s; very short ones (0.4–0.66 s) made the camera disappear
  for 67–111 s (4 of 4). The tools keep at least 3 s.
- A restart can be seen from the laptop without touching the camera: after a
  session the camera returns as USB storage in about 0.8 s, after a crash in
  9–12 s (`a7r.usbwatch`, matched against `/proc/uptime` and `/proc/klog`).
- After a resume from the snapshot `/proc/uptime` starts at about 57 s, and it
  does not advance during a suspend.
- Linux RAM per the kernel command line in the firmware
  (`0800_appli/setting/kemco.txt`): `mem=256M@0x80000000` with reserved areas
  0x80000000+0x28000, 0x82D90000+0x13B1000 (klog at 0x834E0000) and
  0x8E680000+0x1980000; the 576 MiB at 0x9C000000 are reserved as a whole. The
  tools refuse MemoryDump anywhere else.

## Open questions

1. ~~Setting value for 1:1 vs 4:3~~ — 3 = 1:1, 0 = 4:3 (camera, 2026-11-09).
2. ~~Are the 1:1 estimate blocks zero in RAM?~~ Yes (§11).
3. ~~Does the camera shoot 1:1 with the blocks filled?~~ JPEG yes (§11). Open:
   RAW and RAW+JPEG (other StillSizeInfo keys), APS-C crop mode (key 11).
4. What sets the sensor crop window per aspect? Needed for a true XPan crop;
   candidates: `libScalarDaemon.so` `FocusAreaPosition::getYUVLayout`,
   `PARAMID_PREVIEW_ASPECT_TYPE`.
5. Origin of inhibit ids `0x94`/`0x95`/`0x96`/`0x414` (menu greying, second layer).
6. Units of `DATSZ` (KiB assumed).
7. Why the shutter-speed overlay does not update in 1:1 (UI layout per aspect?).
8. Making the 1:1 state survive a battery pull without flashing (e.g. a PMCA
   app that re-applies the RAM fixes), and the Aspect Ratio menu entry.
