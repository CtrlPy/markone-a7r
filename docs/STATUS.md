# Where this project stopped (2026-11-10)

Development is **paused** by the maintainer. This page is the hand-over for
anyone who wants to continue on an ILCE-7R (or try the same on an A7 / A7S).
Read [CLAUDE.md](../CLAUDE.md) (goals, hard rules, risk tiers) and
[AGENTS.md](../AGENTS.md) (workflow) before touching a camera.

## What works

On one ILCE-7R, firmware 3.20, nothing flashed:

- **True 1:1 stills.** Square live view on LCD and EVF, shot counter shown,
  Image Size L/M/S selectable, JPEGs 4912×4912 / 3200×3200 / 2448×2448,
  Sony's metadata says `AspectRatio: 1:1`. It is a crop of the sensor, not a
  squeezed frame.
- **3:2 and 16:9** keep working as stock.
- How: three steps, all through Sony's own service-mode commands (no shell, no
  terminal). Full procedure in
  [findings/aspect-ratio.md §11](findings/aspect-ratio.md):
  1. Backup.bin: 1:1 geometry (`a7r.formats square`) and aspect setting
     `0x01070012 = 03` (`a7r.stage1 --mode service`). These persist.
  2. RAM: the nine 1:1 JPEG estimate blocks (`a7r.mprphys --fill`).
  3. RAM: a 4-byte patch in `libObj.so` for the Image Size menu
     (`a7r.codepatch --scan`).

## What does not work yet

| Item | State | Where to start |
| --- | --- | --- |
| Survive a battery pull | RAM steps 2–3 are lost; they survive the power switch only | [findings/persistence.md](findings/persistence.md) |
| Aspect Ratio menu entry for 1:1 | List fixed at start-up from the UI model type `0x01070316`; 1:1 is set through the service channel | aspect-ratio.md §9, persistence.md §5 |
| Shutter-speed overlay in 1:1 | Does not follow the dial while turning (the speed itself is applied) | aspect-ratio.md §11, open question 7 |
| RAW and RAW+JPEG in 1:1 | Not tested; they use other `StillSizeInfo` keys | aspect-ratio.md §10, open question 3 |
| APS-C crop mode in 1:1 | Not tested (key 11) | aspect-ratio.md §10 |
| XPan 65:24 | Output size alone gives a squeezed 16:9 frame; the sensor crop window per aspect is not found | aspect-ratio.md §8, open question 4 |
| 4:3 | Known hidden value `0`, not worked on | aspect-ratio.md §5 |
| 30-minute video limit | Not worked on | OpenMemories-Tweak #84 |

## Persistence: what is known

The owner's criterion was that a format must survive both the power switch
and a battery pull. Findings ([persistence.md](findings/persistence.md)):

- **No app can do it.** The camera sends apps a broadcast on power-off only,
  never on power-on, and Android resumes from the boot snapshot. An app could
  re-apply the RAM fixes only when opened by hand after each battery pull, and
  whether it can write the camera process's memory is unverified.
- **Any firmware update resets the 1:1 geometry**, even re-installing the
  official 3.20, because those Backup.bin properties are unprotected and the
  updater takes them from its template. That makes the official updater a
  full rollback for the settings side, not a way to persist anything.
- **The only route found** that would survive a battery pull: an update whose
  Backup.bin templates (`0110_backup`) carry the 1:1 geometry, so the post-update
  cold boot computes the shot-counter estimates itself and the new snapshot
  keeps them. `fwtool pack` of the unmodified files reproduces Sony's DAT byte
  for byte, so such a build would differ only in the templates and their CRC
  file. **Not built, not flashed.** The Image Size patch is code and would
  still be RAM-only.

## Risks you take if you continue

- **Service terminal.** Sony-PMCA-RE's `serviceshell` crashed this camera's
  kernel after about half of the sessions; the camera restarts and drops RAM
  changes and unsaved settings. Use only the terminal-free tools and stay in
  service mode for at least 3 s ([aspect-ratio.md §12](findings/aspect-ratio.md)).
  Check each session with `a7r.usbwatch`.
- **RAM writes** go only to pages verified in full first, inside ordinary
  Linux RAM. The tools enforce both; do not bypass them.
- **Backup.bin is persistent.** Back it up first (`a7r.stage0`); write only
  mapped properties, with read-back.
- **Flashing is high risk.** Repacked `nflasha15` images have bricked an
  ILCE-5000 and an ILCE-7RM2 with no known recovery
  ([prior art](findings/community-prior-art.md)). The templates-only update
  above changes no filesystem image, but it is still a full flash: a failure
  mid-update, a refused same-version install (the camera checks the version
  before writing; whether 3.20 over 3.20 is accepted is unknown) or a bad
  template could leave the camera needing the official updater, or worse. Use
  a power source that cannot fail.
- **Never write the warm-boot image** (`nflasha5`, `/wbi`). `a7r.wbidrop` exists
  for the record and has never been run.
- **Never redistribute Sony firmware or binaries**, including dumps and
  repacked DATs.

## Suggested next steps, lowest risk first

1. Static: why the shutter-speed overlay freezes in 1:1 (on-screen layout per aspect).
2. Camera, controlled risk: RAW and RAW+JPEG in 1:1 with the current RAM fixes
   (check the counter and the ARW; `StillSizeInfo` keys other than 0).
3. Static: the sensor crop window per aspect (`libScalarDaemon.so`
   `FocusAreaPosition::getYUVLayout`, `PARAMID_PREVIEW_ASPECT_TYPE`) for XPan.
4. Static: the updater's template choice (`libupdaterbody.so`) and the
   same-version check, before anyone considers the templates-only update.
5. Only by a deliberate decision: the templates-only update (high risk).

## Reproduce from scratch

1. Extract and unpack your own official 3.20 updater (README, "Extract the firmware yourself").
2. `.venv/bin/python -m pytest` (345 tests; firmware tests run when `fw/out` exists).
3. Camera tools need `fw/Sony-PMCA-RE` and its venv (`fw/pmca-venv`, plus
   `pyelftools`); see AGENTS.md. Each module's docstring explains its checks.

Every experiment, including the failures and the corrections of wrong
conclusions, is in [LOG.md](LOG.md).
