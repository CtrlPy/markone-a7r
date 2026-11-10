# CLAUDE.md — a7r-formats

Brief for any Claude (or human) session working in this repo. Read it fully before doing anything that touches the camera.

## The idea

The original Sony A7R (ILCE-7R, 2013, firmware 3.20, final) is small, light and still takes excellent photos. Its owner composes in formats other than 3:2, but the camera only offers **3:2 and 16:9**. Newer Sony bodies have an "Aspect Marker" (1:1, 5:4, 4:3, 16:9, 1.91:1, 2.35:1); the A7R never got it.

**Goal:** let the A7R shoot in other aspect ratios, with the frame visible live on the LCD and EVF, so the photographer composes for the final format instead of cropping later.

Target formats (owner's priorities, 2026-11-10):
1. **1:1** — main goal (hidden native mode on the A7R).
2. **XPan 65:24** — next; it must be a real crop, not a scaled 16:9 frame.
3. **3:2** — must keep working exactly as stock.
4. **16:9** — may serve as the experimental slot for XPan.

4:3 is a known hidden mode but not a priority. 5:4, 4:5, 6:7, half-frame, portrait variants and a custom ratio are ideas, not an approved roadmap.

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
- **Risk tiers (owner's policy, 2026-11-10).** Keeping the camera working comes first, but real experiments are expected:
  - *Low risk* — static analysis; read-only diagnostics through tools already proven on this camera (Backup.bin reads, service-shell reads, `/proc/<pid>/mem` reads); checks of confirmed stock functions. Allowed within an approved plan.
  - *Controlled risk* — RAM-only patches, runtime state changes, stock API calls, writes to Backup.bin properties we have already mapped, runtime re-initialisation, tests of hidden formats. Allowed after a risk assessment and the owner's approval. Each one needs: an exact target and expected behaviour; addresses, original bytes and values checked against 3.20; a backup of the affected data; the minimum number of changes; a read-back; a rollback and stop criteria. Never chain several unverified changes, and never run one whose effect on persistent storage is unknown.
  - *High risk — not used in the current direction* — firmware flashing, direct NAND partition writes, bootloader/kernel/system partition changes, `a7r.wbidrop` or any other invalidation of the warm-boot image, forced cold boot by changing the flash snapshot, anything whose recovery could need reflashing or hardware access. Do not propose these as a practical next step without a separate decision by the owner.
- **Nothing is reversible by assumption.** RAM patches survive a normal power-off (the power switch suspends to RAM); only a crash or a battery pull clears them. `Backup.bin` is persistent. Check reversibility for the specific mechanism every time.
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
- `nflasha5` — not unpacked by fwtool (37 MB in the update). On the camera it is the 60 MiB "Warm Boot Image" mounted as `/wbi` (header magic `WBI1`): the snapshot the camera resumes from on every boot, including after a battery pull. Never write to it (see risk tiers).
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

Outcome (camera, 2026-11-09): the aspect setting is `0x01070012` (1 = 3:2, 2 = 16:9, 3 = 1:1, 0 = 4:3). Value 3 gives a square live view; shooting is blocked by a shot counter of 0. Current state, evidence and open questions: [docs/findings/aspect-ratio.md](docs/findings/aspect-ratio.md); every experiment: [docs/LOG.md](docs/LOG.md).

## Roadmap (risk order)

**Stage 0 — tooling and backup (no writes). Done 2026-11-09.**
- Done with `a7r.stage0` through Sony-PMCA-RE updater mode (nothing installed on the camera): `Backup.bin` and a full `/dev/nflasha` dump, kept off-card with hashes. OpenMemories-Tweak and telnet were not needed.
- Commit only hashes and notes, never the dump.

**Stage 1 — settings level. Done for 1:1 and the 16:9 slot; reached its limit.**
- Aspect setting found (`0x01070012`), 1:1 geometry and JPEG estimates written with `a7r.stage1` (before/after read-back), XPan output sizes tried in the 16:9 slot and rolled back.
- Result: square live view, but the camera will not shoot in 1:1 (counter 0), and PXSZ only sets the output size, not the crop.
- Not tried yet: the Remote Camera / Web API (`orb-server`, `libScalarDaemon.so`), which may read or set the aspect without the menu.

**Stage 2 — static analysis. Ongoing.**
- Ghidra (headless scripts in `tools/ghidra/`) on `libObj.so`, `CautionConfig.so`, `libmprctrl.so`, `libmpr.so`. Known so far: the Image Size gate (libObj), the Aspect Ratio item list chosen at init from the model type (CautionConfig), and the shot-counter tables (libmprctrl/libmpr, `a7r/mprtable.py`).
- Open: how the live-view frame and the sensor crop window are set per aspect (needed for a true XPan crop).

**Stage 3 — dynamic analysis, RAM only. In progress.**
- Access: the Sony service ("senser") mode terminal through Sony-PMCA-RE; `a7r.stage3` runs allow-listed read-only commands.
- RAM writes go only through Sony's own service-mode memory command at the physical address of a page that was first verified (`a7r.physprobe`). Running our own binaries on the camera reset it twice, even read-only, so we no longer do it.
- RAM patches survive a normal power-off (suspend to RAM) and are cleared by a crash or a battery pull, which resumes from the warm-boot snapshot.

**Stage 4 — fallback / extension: our own PMCA app "Formats"** (OpenMemories-Framework, Java, Android 2.3 API):
- Live view with masks for all target formats, wheel to switch, remembers last format.
- Writes an `.xmp` sidecar with crop for each RAW.
- Reference apps that already drive live view: obs1dium/focusbracket, jonasjuffinger/TimeLapse.
- Limitation: works only while the app is running.

**Stage 5 — patched firmware (last resort, on hold).**
- Repack via fwtool `pack` from the user's own official update; minimal diffs; documented recovery path (official updater, then UART if ever needed).
- On hold: repacked `nflasha15` images have bricked an ILCE-5000 and an ILCE-7RM2 with no known recovery ([prior art](docs/findings/community-prior-art.md)). This stage, and anything that touches the warm-boot image, is high risk and needs a separate decision by the owner.

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
- Laptop with Fedora Linux, micro-USB cable, SD card dedicated to experiments.

## Repo layout and workflow

See [AGENTS.md](AGENTS.md) for the layout, tools and engineering workflow (TDD,
commits, verification rules). Static findings so far: [docs/findings/aspect-ratio.md](docs/findings/aspect-ratio.md).
