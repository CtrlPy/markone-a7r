# AGENTS.md — how work is done in a7r-formats

Rules for every contributor, human or agent. Project goal, roadmap and the
camera safety rules are in [CLAUDE.md](CLAUDE.md); read both before starting.

## Non-negotiables

1. Never commit Sony firmware, dumps, extracted binaries or Backup.bin images.
   Test fixtures are built synthetically (`tests/bkbuilder.py`). Facts derived
   from firmware (ids, offsets, dimensions) are fine to publish.
2. Nothing is written to a camera without a fresh off-card backup and the
   owner's explicit go. Stages in CLAUDE.md are followed in order.
3. Every experiment, including failures, gets a row in `docs/LOG.md`.

## Engineering workflow

- **TDD.** Write the test first, watch it fail for the right reason, make it
  pass, refactor. Bugs get a reproducing test before the fix.
- **Verify reverse-engineering claims with data.** A structure layout or a
  meaning is accepted only when a measurable invariant holds (e.g. the
  `{id, name}` table layout was chosen because JPEG size estimates become
  consistent). Pin such facts with a test in `tests/test_firmware_integration.py`.
- **Confirm the code that runs before patching it.** Check `/proc/<pid>/maps`
  (and inodes) on the camera: the menu classes exist both in
  `cmn_view_processDataMgr.so` (never loaded) and inside `libObj.so` (the one
  that runs). A patch to an unloaded copy changes nothing.
- **Tests.** `.venv/bin/python -m pytest`. Firmware tests are marked
  `firmware` and skip when `fw/out` is absent.
- **Git.** GitHub Flow (feature branches off `main`), Angular Conventional
  Commits, small atomic commits, tests green before each commit. No push,
  merge or release without the owner's approval.
- **Language.** Code, docs and commits in English; talk to the owner in Ukrainian.

## Layout

- `a7r/` — Python package.
  - Offline: `backup` (Backup.bin parser, dump/diff CLI), `bkid` (BKID name → id
    tables from ELF files), `ids` (geometry property ids), `formats` (plan
    geometry values and rollbacks for a hidden aspect), `mprtable` (layout of
    the shot-counter tables), `patch` / `patches` (SHA-256-checked byte patches).
  - Camera, terminal-free (use these): `stage0` (read-only backup, updater
    mode), `stage1` (allow-listed Backup.bin writes with read-back),
    `mprphys` (check and fill the 1:1 shot-counter estimates in RAM),
    `codepatch` (verified code patch in RAM, `--scan` finds the page),
    `usbwatch` (restart check from the laptop's kernel log).
  - Camera, service terminal (crashes the camera often, reference only):
    `stage3` (read-only shell commands), `physmem` / `physprobe`, `mprdump`.
  - Kept for the record, not used: `mempatch` (needs our own binary, which
    resets the camera), `overlay` (targets a library that is never loaded),
    `wbidrop` (writes the warm-boot image: high risk, never run).
- `native/a7rpoke/` — static ARM helper; running it reset the camera, not used.
- `tools/` — standalone scripts (`extract_dat.py`) and headless Ghidra scripts (`tools/ghidra/`).
- `tests/` — unit tests on synthetic data, firmware integration tests.
- `docs/findings/` — findings with reproduction commands; each says what is
  confirmed on the camera and what is still a hypothesis.
- `docs/LOG.md` — experiment log. Rows are never rewritten; a later row corrects an earlier one.
- `fw/`, `dumps/`, `work/`, `ghidra_projects/`, `.venv/` — local only,
  git-ignored. Reference clones (fwtool.py, Sony-PMCA-RE, OpenMemories-Tweak)
  live in `fw/`.

## Environment

Fedora Linux, Python 3.11+ venv in `.venv` (`pip install -e '.[dev]'`).
Camera tools run from a second venv that holds the Sony-PMCA-RE requirements
(`fw/pmca-venv`, Python 3.12) with `PYTHONPATH=.`; it also needs `pyelftools`.
Static analysis: `strings`, pyelftools, capstone for quick checks; Ghidra
12.1.4 (the build REA verifies against, JDK 21+) for decompilation and call
graphs, driven headless (`support/analyzeHeadless`) or through the REA MCP
server / CLI (`npx rea-agents@6.8.0`, Node >= 24.22.1, `GHIDRA_INSTALL_DIR`
set). Hand-rolled capstone call-target naming proved unreliable on these
stripped Thumb-2 libraries; use Ghidra for anything that depends on callees.
Decompiler output can drop arguments (seen on `WrapperSettingUtil::isInhOn`):
confirm constants in the disassembly.

Native helper for the camera: `native/a7rpoke` (C, static). Build with
`mise exec zig@0.13.0 -- zig cc -target arm-linux-musleabi -mcpu=cortex_a5 -static -Os -o work/bin/a7rpoke-armv7 native/a7rpoke/a7rpoke.c`;
host tests compile it for x86 and run it on a scratch file. The camera runs
BusyBox 1.13.4 (no `dd conv=`, no `id`/`which`).

## Handoff

Session handoffs and private working notes are kept outside the repository
by the maintainer. The repo carries only what the community needs.
