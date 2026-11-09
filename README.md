# a7r-formats

Bringing extra aspect ratios (1:1, 4:3, 5:4, 6:7, 2.35:1, XPan 65:24 and more) to the original Sony A7R (ILCE-7R), and maybe its siblings A7 and A7S.

The first-gen A7 bodies are small, light and still great. They deserve a bit more love.

**Status:** research. Firmware 3.20 unpacks and decrypts; the userland contains `STILL_ASPECT_1_1` / `STILL_ASPECT_4_3` and 1:1 image-size UI nodes. Next step: find the aspect setting in `Backup.bin` and test hidden values on a real camera.

See [CLAUDE.md](CLAUDE.md) for the full plan, rules and findings, and [docs/LOG.md](docs/LOG.md) for experiments.

## Extract the firmware yourself

We do not distribute Sony firmware. Download the official ILCE-7R 3.20 updater from Sony, then:

```
python3 tools/extract_dat.py Update_ILCE7RV320.exe FirmwareData_ILCE7RV320.dat
git clone https://github.com/ma1co/fwtool.py
python3 fwtool.py/fwtool.py unpack -f FirmwareData_ILCE7RV320.dat -o fw/out
```

Expected SHA-256 of `Update_ILCE7RV320.exe`: `a7b581b5f9ba422c5bf4dcee61b770c5133f15a271e5860f43753a352edbc929`

## Disclaimer

Experimental. Anything you do to your camera is at your own risk. Back up first. Not affiliated with Sony.

## Credits

Built on the work of ma1co (fwtool.py, Sony-PMCA-RE, OpenMemories) and the nex-hack project.
