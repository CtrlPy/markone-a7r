# Prior art from other Sony camera hackers (checked 2026-11-09)

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
- **Self-repacked update bricked an ILCE-7RM2** — issue #488 (Sep 2026):
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
   `WARMBOOT` and the 1:1 counter.
