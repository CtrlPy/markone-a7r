# a7r-formats

Bringing extra aspect ratios (1:1, 4:3, 5:4, 6:7, 2.35:1, XPan 65:24 and more) to the original Sony A7R (ILCE-7R), and maybe its siblings A7 and A7S.

The first-gen A7 bodies are small, light and still great. They deserve a bit more love.

**Status:** research, no camera writes yet. Firmware 3.20 unpacks and decrypts. The still image geometry for every aspect is stored in the camera settings (`Backup.bin`), and on the A7R the 1:1 and 4:3 slots exist but are empty; the GUI already enumerates four aspects behind a per-value gate. Next step: find the id of the current aspect setting on a real camera and try filling the 4:3 slots. Details in [docs/findings/aspect-ratio.md](docs/findings/aspect-ratio.md).

See [CLAUDE.md](CLAUDE.md) for the full plan and hard rules, [AGENTS.md](AGENTS.md) for how we work, and [docs/LOG.md](docs/LOG.md) for experiments.

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

- `a7r.backup` — read-only parser for `Backup.bin` (BK2/BK4): dump properties, diff two files.
- `a7r.bkid` — recover `BKID_*` name → property id tables from firmware libraries.
- `tools/extract_dat.py` — carve the DAT out of the 2023-style updater exe.

## Disclaimer

Experimental. Anything you do to your camera is at your own risk. Back up first. Not affiliated with Sony.

## Credits

Built on the work of ma1co (fwtool.py, Sony-PMCA-RE, OpenMemories) and the nex-hack project.
