# Aspect ratio: static findings (ILCE-7R 3.20)

All findings are from the official 3.20 updater, unpacked locally (see README).
No camera was involved yet. Reproduce with the commands under each section.

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

## Open questions

1. Backup.bin id of the *user's current* still aspect setting. Not named in any
   table; found fastest on the camera: dump Backup.bin with 3:2, switch to 16:9,
   dump again, `python -m a7r.backup diff`.
2. Origin of inhibit ids `0x94`/`0x95`/`0x96`/`0x414`: a data table (patchable
   in Backup.bin or a config file) or code.
3. Whether the live view mask for 16:9 is also data driven (candidates:
   `libScalarDaemon.so` `FocusAreaPosition::getYUVLayout`, `PARAMID_PREVIEW_ASPECT_TYPE`).
4. Units of `DATSZ` (KiB assumed) and whether `PXSZ` alone is enough for the
   JPEG encoder, or the sensor readout / crop tables need values too.

## Candidate Stage 1 experiment (needs owner approval, camera, fresh backup)

1. Find the aspect setting id (question 1).
2. Write 4:3 geometry into `PXSZ_STL_{L,M,S}_4_3`: e.g. L 6544×4912
   (width rounded to a multiple of 16), M 4256×3200, S 3264×2456. Copy the
   matching DATSZ estimates scaled by pixel count.
3. Set the aspect value to 1 (4:3), check menu, live view, JPEG and ARW.
4. Restore the saved Backup.bin.
