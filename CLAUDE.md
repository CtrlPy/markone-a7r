# CLAUDE.md — a7r-formats

Brief for any Claude (or human) session working in this repo. Read it fully before doing anything that touches the camera.

## The idea

The original Sony A7R (ILCE-7R, 2013, firmware 3.20, final) is small, light and still takes excellent photos. Its owner composes in formats other than 3:2, but the camera only offers **3:2 and 16:9**. Newer Sony bodies have an "Aspect Marker" (1:1, 5:4, 4:3, 16:9, 1.91:1, 2.35:1); the A7R never got it.

**Goal:** let the A7R shoot in other aspect ratios, with the frame visible live on the LCD and EVF, so the photographer composes for the final format instead of cropping later.

Target formats, in priority order: 1:1, 4:3, 5:4 / 4:5, 6:7, 16:9 (exists), 2.35:1, 65:24 (XPan), half-frame, plus portrait variants and a custom ratio.

Definition of done (per format):
1. Live view (LCD + EVF) shows the format clearly (crop or mask).
2. The JPEG comes out in that format.
3. The RAW (.ARW) carries the intended crop so Lightroom / Capture One open it cropped (non-destructively). If the camera itself can't do that, a sidecar `.xmp` with `crs:Crop*` values is acceptable.
4. The setting survives power-off, or can be restored in two button presses at most.
5. Fully reversible; nothing makes the camera less usable than stock.

Secondary goals, only after the main one works: the 30-minute video limit (OpenMemories-Tweak does not lift it on this model, see ma1co/OpenMemories-Tweak issue #84), and anything else useful to other first-gen A7/A7R/A7S owners.

This is meant to be a public, community project. Other owners of old Sony bodies may join.

## Hard rules

- **Never redistribute Sony firmware or binaries.** Not in commits, not in issues, not as test fixtures. Publish our own code, patches, scripts and notes only; users supply their own official updater. `.gitignore` already excludes `*.exe`, `*.dat`, `*.fdat`, `*.tar`, `fw/`, `dumps/`. Same approach as Hearts-Ace/sony-a7r5-custom-firmware.
- **Never write to the camera without a fresh backup** (full `nflasha` dump + `Backup.bin`) stored off the SD card, and only after the owner explicitly says go.
- **Work in risk order, never skip a stage** (see Roadmap). In-memory and settings-level changes come before any flashing.
- **Ask the owner before any irreversible step:** writing a modified firmware, writing to flash partitions, writing unknown Backup.bin keys, enabling telnet on a camera that will leave the house.
- Keep a log in `docs/LOG.md`: what was tried, on which firmware, result. Negative results are valuable.
- The owner's language is Ukrainian; talk to him in Ukrainian. Repo docs, code and commit messages in English so the community can follow.

## Why this camera is a good target

- Platform **CXD90014** (BIONZ X generation, Linux 3.0 + Android 2.3 subsystem for PlayMemories apps).
- Firmware is **decryptable** with ma1co/fwtool.py and **not cryptographically signed** like the newer CXD90045 / CXD90057 bodies (per ma1co/Sony-PMCA-RE README).
- Sony-PMCA-RE can run our own code in **updater mode** without touching the installed firmware, and install Android apps (PMCA).
- OpenMemories-Tweak exposes telnet/adb and edits `Backup.bin` settings.

## What we already know (verified 2026-11-09 on Update_ILCE7RV320.exe)

Updater: `Update_ILCE7RV320.exe`, 208,959,544 bytes, SHA-256 `a7b581b5f9ba422c5bf4dcee61b770c5133f15a271e5860f43753a352edbc929`. It is Sony's 2023 re-packaged "System Software Updater Package" (uncompressed, Compression=False). fwtool.py fails on it with `Unknown exe file`; use `tools/extract_dat.py` first, then fwtool on the DAT.

`fwtool` output, `config.yaml`: `crypterName: CXD90014`, `model: 0x41030034`, `version: '3.20'`, updater USB PID `0x054C:0x03E2`.

Firmware layout (inside `firmware.tar_unpacked/`): `0100_config`, `0110_backup`, `0300_partconf`, `0600_gps`, `0630_ca`, `0640_darwin`, `0650_prfile`, `0700_part_image`, `0800_appli` (incl. `setting/init_bk.bak`), `9000_loader`.

Partitions in `0700_part_image/dev/`:
- `nflasha3` — kernel `vmlinux.bin`, `initrd.img`, `av-cam.bin`, `sabin`, lens properties.
- `nflasha5` — not unpacked by fwtool (37 MB), unknown.
- `nflasha7` — main rootfs (`android/`, `setting/`, `etc/`, ...).
- `nflasha15` — camera userland: `bin/` (`orb-server` = remote/Web API, `bk.elf`, `NsBkSet.elf`, ...), `lib/` (GUI engine, imaging libs), `scenario/`.
- `nflasha16` — Android system (`app/`, `framework/`, `build.prop`).

**Lead #1 — hidden aspect ratios.** Strings in the A7R 3.20 userland show the platform knows more formats than the menu offers:
- `lib/libObj.so`: `DefStruct::STILL_ASPECT_1_1`, `STILL_ASPECT_4_3`, `STILL_ASPECT_3_2`, `STILL_ASPECT_16_9`, `STILL_ASPECT_17_9`; same set for `MOVIE_ASPECT_*`.
- `lib/CautionConfig.so`: GUI nodes `cmnViewSettingNodeStillImageSizeSizeL1_1_MR`, `...M1_1_MR`, `...S1_1_MR` (1:1 image sizes L/M/S).
- `lib/libmprctrl.so`: `BKID_IMAGING_DATSZ_..._1_1_...` data-size tables.
- `bin/orb-server`: strings `1:1`, `4:3`, `3:2`, `16:9`; params `PARAMID_CAMSETTING_IMAGE_ASPECT_RATIO`, `PARAMID_SYS_DATA_STILL_FORMAT_ASPECT_SET` / `_ACT`, `PARAMID_PREVIEW_ASPECT_TYPE`, `PARAMID_BKUP_DEVICE_IMAGER_ASPECT`.
- `lib/wrapperImageAspect.so` exists.

Caveat: this is shared platform code (same libs ship on RX100-class bodies that do have 1:1 / 4:3), so presence ≠ enabled on A7R. But if the pipeline is there, the cheapest win is flipping the aspect setting to a hidden value. That is stage 1.

## Roadmap (risk order)

**Stage 0 — tooling and backup (no writes).**
- Set up Sony-PMCA-RE (`pmca-console` / `pmca-gui`) on the owner's laptop; confirm the camera is detected (`info`).
- Install OpenMemories-Tweak via PMCA-RE. Enable telnet only for the session.
- Dump: `dd if=/dev/nflasha of=/android/mnt/sdcard/DUMP.DAT bs=1M` (Android 2 path), copy off-card, hash it. Also save `Backup.bin` (location: find it in the dump / via Tweak; see OpenMemories-Tweak source for how it reads it).
- Commit only hashes and notes, never the dump.

**Stage 1 — settings level (reversible).**
- Map Backup.bin: find the property id for still aspect ratio (start from `PARAMID_SYS_DATA_STILL_FORMAT_ASPECT_SET`, `bk.elf`, `NsBkSet.elf`, OpenMemories-Tweak's backup code).
- Read current value with 3:2 and with 16:9 selected, diff them.
- With owner approval, write the candidate values for 4:3 and 1:1. Check live view, JPEG, ARW, menu. Revert.
- Also try the Remote Camera / Web API (`orb-server`): `getSupportedStillSize`/`setStillSize` style calls may reveal or accept hidden aspects without touching flash.

**Stage 2 — static analysis.**
- Ghidra on `libObj.so`, `CautionConfig.so`, `libmprctrl.so`, `wrapperImageAspect.so`, GUI engine libs: where is the list of selectable aspects built per model, and what gates 1:1/4:3.
- Find how live view is cropped / masked for 16:9; that's the hook for custom ratios.

**Stage 3 — dynamic analysis (telnet).**
- Processes, logs (`appdbglv.sh`), how settings are applied at runtime. In-memory patches only (lost on reboot).

**Stage 4 — fallback / extension: our own PMCA app "Formats"** (OpenMemories-Framework, Java, Android 2.3 API):
- Live view with masks for all target formats, wheel to switch, remembers last format.
- Writes an `.xmp` sidecar with crop for each RAW.
- Reference apps that already drive live view: obs1dium/focusbracket, jonasjuffinger/TimeLapse.
- Limitation: works only while the app is running.

**Stage 5 — patched firmware (last resort, owner approval required).**
- Repack via fwtool `pack` from the user's own official update; minimal diffs; documented recovery path (official updater, then UART if ever needed).

## Tools

- ma1co/fwtool.py — unpack/pack firmware (`fwtool unpack -f FirmwareData_ILCE7RV320.dat -o out`).
- ma1co/Sony-PMCA-RE — USB: info, app install, updater-mode code exec, service mode, firmware dump.
- ma1co/OpenMemories-Tweak — settings, telnet/adb.
- ma1co/OpenMemories-Framework — base for our PMCA app; `docs/Cameras.md` lists supported bodies.
- Ghidra (ARM 32-bit LE, ELF, stripped).
- Related work on newer bodies, for methods not code: leogenot/sony-a7iv-feature-research (settings-backup property edits), DavidBuchanan314/ILCE-7M4-RE, Erlla/sony-a7m4-custom-firmware, QAQLeonard/a7c2-fl23-research.

## Hardware on hand

- Sony A7R (ILCE-7R), firmware 3.20.
- HDMI capture card (owner has it). Dummy battery NP-FW50 → USB-C PD is being bought: use it during any long telnet/update session so power never drops.
- Laptop (OS: ask the owner), micro-USB cable, SD card dedicated to experiments.

## Repo layout

- `tools/extract_dat.py` — carve the DAT out of the 2023-style updater exe.
- `docs/LOG.md` — experiment log.
- `docs/` — findings (partition map, Backup.bin ids, function notes).
- `fw/`, `dumps/` — local only, git-ignored.
