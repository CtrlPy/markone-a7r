# Prior art from other Sony camera hackers (checked 2026-11-09, updated 2026-11-10)

Summary of public reports relevant to this project. Links are primary
sources unless noted; "unverified" means a single self-report.

## Same platform (CXD90014 / BIONZ X)

- **Patched firmware bricked an ILCE-5000** — Sony-PMCA-RE issue #752
  (Nov 2026). Two bytes changed in `/usr/lib/viewUnified2.so`, `nflasha15`
  block re-encoded, `part_image.sum` updated, flashed with
  `pmca-console firmware`: "Done", then a boot loop enumerating only as USB
  charger 054C:0994. The **same change as a live RAM patch of `im.elf`
  worked**. The reporter suspects the warm-boot snapshot (`nflasha5`, `WBI1`)
  caches the stock nflasha15 block table. Unrecovered, unanswered.
  https://github.com/ma1co/Sony-PMCA-RE/issues/752
- **Self-repacked update bricked an ILCE-7RM2** — issue #488 (opened 2024
  for a bricked A6000; the ILCE-7RM2 report is a comment from Sep 2026):
  accepted and "Done", then LED error, no USB. Cause: own LZ77 encoder did not
  pad blocks to 512 bytes. "Please don't try this without a debug serial cable
  in hand." Unrecovered. https://github.com/ma1co/Sony-PMCA-RE/issues/488
- **UART**: 115200 8N1 output on an A6000 through the 15-pin multi-terminal
  micro-USB connector with a special cable (#488). Input unknown.
- **Stuck modes recovered**: A6300/A7S stuck in service mode → `rm -f
  /setting/mode/* /setting/sen/*` (#683); NEX-C3 stuck in updater production
  mode → service-mode ProductInfo ApplicationMode command + battery out (#757);
  AX33 → battery pull (#634).
- **Unrecovered bricks after deleting updater-mode files** (#232, #373).
- No public report of unlocking hidden aspect ratios on any Sony body, and no
  documented `fwtool.py pack` workflow.

## Newer bodies (methods only)

- leogenot/sony-a7iv-feature-research: service mode, Backup.bin property
  writes, offline static analysis; features gated in several layers (display
  vs. input vs. product class); changes need a battery-out cold boot.
- ma1co/Sony-PMCA-RE #756 (A7 IV): a hidden menu item gated by one backup
  property, found by diffing region seed images and disassembling the gate.
- QAQLeonard/a7c2-tools: every write read back; "battery out ≥1 minute"
  before changes apply; "matching readback does not establish boot safety".
- Erlla/sony-a7m4-custom-firmware: custom firmware for A7 IV incl. a custom
  aspect-ratio module (different, signed platform; self-signed updates;
  fastboot via RP2040 on the multi-interface port).
- DavidBuchanan314/ILCE-7M4-RE, Hearts-Ace/sony-a7r5-custom-firmware:
  hardware boot paths and build pipelines for newer SoCs; WBI listed as not
  yet validated.

## What this means here

1. Our method (service mode, Backup.bin, Ghidra, RAM patches, read-back,
   backups) is the same one these projects use.
2. Repacking `nflasha15` (where `libObj.so` and `CautionConfig.so` live) has
   bricked two CXD90014-era bodies without a known recovery. Do not flash a
   modified `nflasha15` before the brick mechanism is understood and a
   recovery path (UART cable) exists.
3. Cheap test first: battery out for ≥1–2 minutes, then check dmesg for
   `WARMBOOT` and the 1:1 counter. Done 2026-11-09: still `WARMBOOT`, counter
   still 0. On the A7R a battery pull does not give a cold boot.

## Search of 2026-11-10: snapshot boot and init-time settings

Looked for any public work on Sony's snapshot boot ("ssboot", `/proc/ssboot`,
`WBI1`, `/wbi`) on CXD90014 or NEX/Alpha bodies, and for runtime re-init of
imaging/MPR settings. About a dozen searches; GitHub issues read directly.

- **Nothing public** on regenerating or bypassing the warm-boot snapshot, or
  on a stock command that re-initialises MPR / imaging without a reboot.
  Sony's original design is in Kaminaga, "Improving Linux Startup Time Using
  Software Resume", OLS 2006 (not read in full here).
- **Newer bodies, property edits.** Sony-PMCA-RE #756 (A7 IV, Nov 2026): one
  Backup.bin property shows a hidden menu item after a plain power cycle; also
  confirmed on an A7S III and an FX3. leogenot/sony-a7iv-feature-research
  lists edits that need a battery-out cold boot. Neither mentions a snapshot,
  so they say nothing about the A7R's behaviour.
- **Aspect ratios.** Erlla/sony-a7m4-custom-firmware adds 17:6, 65:24, 5:4 and
  7:6 on the A7 IV (JPEG/HEIF cropped, RAW full frame) through flashed custom
  firmware on a different, key-compromised platform. No public work found on
  the shots-remaining counter or "no space on memory card" on any body.
- **30-minute limit on the A7R.** OpenMemories-Tweak #84 (2016, open): the
  Backup.bin limit is changed but the A7R still stops at 29:50. This fits
  another value read once at init or kept outside Backup.bin.

What this means here: there is no ready-made public answer. The snapshot
problem has to be solved locally, and the RAM-only route (patching the data
that was computed at init, see aspect-ratio.md §10) avoids the snapshot
altogether.
