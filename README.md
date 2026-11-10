# a7r-formats

Extra aspect ratios for the original Sony A7R (ILCE-7R, firmware 3.20), and maybe later its siblings A7 and A7S. The first-gen A7 bodies are small, light and still great. They deserve a bit more love.

The A7R only offers 3:2 and 16:9. Its firmware is shared platform code that also knows 1:1 and 4:3, and the camera can be made to use them. The goal is to compose for the final format with the frame visible on the LCD and EVF, and get the file in that format.

## Status (2026-11-10)

Research project, actively testing on one camera. No firmware has been flashed.

What works, confirmed on the camera:
- **Hidden 1:1 aspect.** Setting the aspect property in `Backup.bin` (`0x01070012 = 3`) gives a square live view on the LCD and EVF, with no errors.
- **1:1 image geometry.** We filled the empty 1:1 pixel sizes and JPEG size estimates in `Backup.bin` (L 4912×4912, M 3200×3200, S 2448×2448).
- **Image Size menu in 1:1.** It works after a 4-byte patch to `libObj.so`, applied in RAM only through Sony's own service-mode memory command.
- **3:2 and 16:9.** Both still work as stock after every experiment.

What does not work yet:
- **1:1 shooting.** The shot counter shows 0 and "no space on memory card", so the camera does not release the shutter. Static analysis points to the cause (see below). A read-only check on the camera and a RAM-only fix are planned.
- **Aspect Ratio menu.** It still lists only 3:2 and 16:9. The list is chosen once at start-up from the model type, so the hidden aspects are set through the service channel instead.
- **XPan 65:24.** Writing XPan output sizes into the 16:9 slot gave a 7360×2720 JPEG, but it is the 16:9 frame squeezed vertically, not a crop. A real XPan crop needs a different crop window, which is still to be found.

**Why the counter is probably 0.** The remaining-shots count divides free space by per-shot size estimates. The camera computes these once at start-up and keeps them in RAM. There is no code path that rebuilds them later. The A7R resumes from a boot snapshot, even after a battery pull, so they were most likely computed while the 1:1 values were still zero. The tables are in the main camera process, and their layout is now known (`a7r/mprtable.py`). Reading them on the camera will confirm or reject this. Details and evidence are in [docs/findings/aspect-ratio.md](docs/findings/aspect-ratio.md); every experiment is in [docs/LOG.md](docs/LOG.md).

Format priorities: **1:1** first, then a true **XPan 65:24** crop. 3:2 must keep working as stock, and 16:9 is the experimental slot for XPan. 4:3 is a known hidden mode but not a priority. Other ratios (5:4, 4:5, 6:7, half-frame, custom) are ideas, not a plan.

## Safety approach

- **Low risk:** static analysis of the firmware, plus read-only diagnostics on the camera (settings reads, process memory reads through the service shell).
- **Controlled risk:** RAM-only patches, writes to known `Backup.bin` properties, and runtime state changes. Each one needs a fresh backup, a pre-check of the exact bytes, a read-back, and a rollback plan. One change at a time.
- **Not used:** flashing firmware, writing NAND partitions, touching the bootloader, kernel or the warm-boot snapshot (`/dev/nflasha5`). Repacked firmware has bricked two cameras of this generation with no known recovery (see [prior art](docs/findings/community-prior-art.md)).

RAM patches are not automatically temporary. On this camera the power switch suspends to RAM, so a patch survives a normal off/on and is cleared only by a crash or a battery pull. `Backup.bin` is persistent storage. See [CLAUDE.md](CLAUDE.md) for the hard rules.

## Extract the firmware yourself

We do not distribute Sony firmware. Download the official ILCE-7R 3.20 updater from Sony, then:

```
python3 tools/extract_dat.py Update_ILCE7RV320.exe FirmwareData_ILCE7RV320.dat
git clone https://github.com/ma1co/fwtool.py
python3 fwtool.py/fwtool.py unpack -f FirmwareData_ILCE7RV320.dat -o fw/out
```

Expected SHA-256 of `Update_ILCE7RV320.exe`: `a7b581b5f9ba422c5bf4dcee61b770c5133f15a271e5860f43753a352edbc929`

## Tools

```
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest            # unit tests; firmware tests run when fw/out exists
.venv/bin/python -m a7r.backup dump Backup.bin [--subsystem 0x5]
.venv/bin/python -m a7r.backup diff before.bin after.bin
.venv/bin/python -m a7r.bkid fw/out/.../lib/libmprctrl.so Backup.bin --grep PXSZ_STL
```

Offline, no camera:
- `a7r.backup` — parser for `Backup.bin` (BK2/BK4): dump properties, diff two files.
- `a7r.bkid` — recover `BKID_*` name → property id tables from firmware libraries.
- `a7r.formats` — plan the `Backup.bin` geometry values for a hidden aspect (and their rollback).
- `a7r.mprtable` — layout of the still-size tables behind the shot counter.
- `a7r.patch`, `a7r.patches` — verified byte patches for the user's own firmware files (SHA-256 checked).
- `tools/extract_dat.py` — carve the DAT out of the 2023-style updater exe; `tools/ghidra/` — headless Ghidra scripts used for the findings.

Camera tools (they use [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE); read each module's docstring first):
- `a7r.stage0` — read-only backup (`Backup.bin` + flash dump) in updater mode.
- `a7r.stage1` — write allow-listed `Backup.bin` properties with before/after verification (`--mode service` keeps RAM state).
- `a7r.stage3` — read-only shell commands over the service-mode terminal.
- `a7r.physprobe` — RAM-only code patch through Sony's service-mode memory command at the physical address, after checking the whole page against the file.
- `a7r.mprdump` — read the shot-counter estimates in the running camera and compare them with what the start-up code would compute from the current `Backup.bin`. Read-only by default; `--fill` writes one 1:1 block at a time in RAM, behind the same checks.

Kept for the record, not recommended:
- `a7r.mempatch` and `native/a7rpoke` — running our own binary reset the camera.
- `a7r.overlay` — the targeted library is never loaded.
- `a7r.wbidrop` — writes to the warm-boot snapshot partition. It is high risk and has never been run.

## Disclaimer

Experimental. Anything you do to your camera is at your own risk. Back up first. Not affiliated with Sony.

## Credits

Built on the work of ma1co (fwtool.py, Sony-PMCA-RE, OpenMemories) and the nex-hack project.
