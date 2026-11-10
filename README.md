# a7r-formats

Extra aspect ratios for the original Sony A7R (ILCE-7R, firmware 3.20), and maybe later its siblings A7 and A7S. The first-gen A7 bodies are small, light and still great. They deserve a bit more love.

The A7R only offers 3:2 and 16:9. Its firmware is shared platform code that also knows 1:1 and 4:3, and the camera can be made to use them. The goal is to compose for the final format with the frame visible on the LCD and EVF, and get the file in that format.

## Status (2026-11-10)

Research project, actively testing on one camera. No firmware has been flashed.

**The A7R now shoots a true 1:1** (as of 2026-11-10, with RAM-only fixes):
- **Live view.** Square on the LCD and EVF, with the 1:1 icon.
- **Shot counter.** Shown as usual.
- **Image Size.** L, M and S can be selected.
- **Files.** JPEGs of 4912×4912 (L), 3200×3200 (M) and 2448×2448 (S). Sony's own metadata says `AspectRatio: 1:1`.
- **Real crop.** Object proportions match a 3:2 shot of the same scene: this is a crop of the sensor, not a squeezed frame.
- **3:2 and 16:9.** They keep working as stock.

How it works, in short:
1. **Settings.** The aspect setting and the empty 1:1 image sizes are written once to the camera's settings (`Backup.bin`); these persist.
2. **RAM fixes.** The camera computes its per-shot size estimates once at start-up and resumes from a boot snapshot, so the 1:1 estimates stay zero (counter 0, "no space on memory card"). We fill them in RAM, and apply a 4-byte RAM patch to `libObj.so` for the Image Size menu.
3. **Persistence.** Both RAM changes survive the power switch (the camera suspends to RAM). A battery pull clears them; then two short service sessions apply them again.

Not working yet:
- **Shutter-speed overlay.** In 1:1 it does not update while the dial is turned. The new speed is applied, so this is a display issue only.
- **Aspect Ratio menu.** It still lists only 3:2 and 16:9 (the list is fixed at start-up), so 1:1 is set through the service channel.
- **RAW and RAW+JPEG in 1:1.** Not tested yet.
- **XPan 65:24.** Writing XPan output sizes into the 16:9 slot gave a squeezed 16:9 frame, not a crop. A real XPan crop needs a different crop window, which is still to be found.

Details and evidence: [docs/findings/aspect-ratio.md](docs/findings/aspect-ratio.md) (§11 for the procedure); every experiment, including the failures, is in [docs/LOG.md](docs/LOG.md).

**Warning for anyone with a first-gen A7/A7R/A7S:** Sony-PMCA-RE's service *terminal* (`serviceshell`) crashed this camera's kernel after roughly half of the sessions over two days. The camera restarts, losing RAM changes and any settings not yet saved. Our camera tools now use only Sony's service commands, without the terminal, and stay in service mode for at least 3 s; see §12 of the findings.

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

Camera tools (they use [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE); read each module's docstring first). The ones marked *terminal-free* use only Sony's service commands:
- `a7r.stage0` — read-only backup (`Backup.bin` + flash dump) in updater mode.
- `a7r.stage1` — write allow-listed `Backup.bin` properties with before/after verification (`--mode service` keeps RAM state; terminal-free).
- `a7r.mprphys` — check the shot-counter estimates in RAM against the formula and fill the 1:1 ones (`--fill SIZE:QUALITY`), through MemoryDump after a full-page check (terminal-free).
- `a7r.codepatch` — apply a verified code patch in RAM (`--scan` finds the library page in RAM first) (terminal-free).
- `a7r.usbwatch` — tell from the laptop's kernel log whether a service session ended in a camera restart.

Uses the service terminal, which crashes the camera often (kept for reference):
- `a7r.stage3` — read-only shell commands.
- `a7r.mprdump`, `a7r.physprobe` — the first versions of the estimate check and the code patch.

Kept for the record, not recommended:
- `a7r.mempatch` and `native/a7rpoke` — running our own binary reset the camera.
- `a7r.overlay` — the targeted library is never loaded.
- `a7r.wbidrop` — writes to the warm-boot snapshot partition. It is high risk and has never been run.

## Disclaimer

Experimental. Anything you do to your camera is at your own risk. Back up first. Not affiliated with Sony.

## Credits

Built on the work of ma1co (fwtool.py, Sony-PMCA-RE, OpenMemories) and the nex-hack project.
