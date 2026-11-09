# Experiment log

| Date | Firmware | What | Result |
| --- | --- | --- | --- |
| 2026-11-09 | 3.20 | fwtool.py on `Update_ILCE7RV320.exe` | Fails: `Unknown exe file` (2023 re-packaged wrapper). |
| 2026-11-09 | 3.20 | `tools/extract_dat.py` → fwtool on DAT | OK. CXD90014, model 0x41030034. Partitions nflasha3/5/7/15/16 unpacked (5 not unpacked). |
| 2026-11-09 | 3.20 | `strings` for aspect | Found `STILL_ASPECT_1_1`, `STILL_ASPECT_4_3` (libObj.so), `StillImageSizeSizeL1_1_MR` nodes (CautionConfig.so), `PARAMID_SYS_DATA_STILL_FORMAT_ASPECT_SET` (orb-server). Not yet known if enabled for A7R. |
