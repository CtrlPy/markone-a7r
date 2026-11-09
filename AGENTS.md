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

- `a7r/` — Python package: `backup` (Backup.bin parser, dump/diff CLI),
  `bkid` (BKID name → id tables from ELF files).
- `tools/` — standalone scripts (`extract_dat.py`).
- `tests/` — unit tests on synthetic data, firmware integration tests.
- `docs/findings/` — verified findings with reproduction commands.
- `docs/LOG.md` — experiment log.
- `fw/`, `dumps/`, `.venv/` — local only, git-ignored. Reference clones
  (fwtool.py, Sony-PMCA-RE, OpenMemories-Tweak) live in `fw/`.

## Environment

Fedora Linux, Python 3.11+ venv in `.venv` (`pip install -e '.[dev]'`).
Static analysis: `strings`, pyelftools, capstone for quick checks; Ghidra
12.1.4 (the build REA verifies against, JDK 21+) for decompilation and call
graphs, driven headless (`support/analyzeHeadless`) or through the REA MCP
server / CLI (`npx rea-agents@6.8.0`, Node >= 24.22.1, `GHIDRA_INSTALL_DIR`
set). Hand-rolled capstone call-target naming proved unreliable on these
stripped Thumb-2 libraries; use Ghidra for anything that depends on callees.
Decompiler output can drop arguments (seen on `WrapperSettingUtil::isInhOn`):
confirm constants in the disassembly.

## Handoff

Session handoffs and private working notes are kept outside the repository
by the maintainer. The repo carries only what the community needs.
