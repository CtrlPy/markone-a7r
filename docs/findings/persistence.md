# Persistence: can 1:1 survive a battery pull? (static, 2026-11-10)

The 1:1 fixes in [aspect-ratio.md §11](aspect-ratio.md) live in RAM. They
survive the power switch (suspend to RAM) and are lost when the battery is
pulled, because the camera then resumes from the warm-boot snapshot. The
owner's criterion for any delivery is that the formats survive both. This
page records what the 3.20 firmware allows. Everything here is static
analysis of the user's own firmware plus behaviour already seen on the camera.
Nothing new was run on the camera.

## Summary

| Route | Survives power switch | Survives battery pull | Writes flash | Status |
| --- | --- | --- | --- | --- |
| Service sessions from a laptop (today) | Yes | No, re-run after a pull | No | Works |
| Our own PMCA app, opened by hand | Yes | No, open the app again after a pull | App install only | Possible, not built; memory access unverified |
| PMCA app that starts by itself at power-on | — | — | — | **Not possible**: nothing starts apps at power-on (§2) |
| Re-install of the official 3.20 update | — | Resets the 1:1 geometry to zero (§3) | Full update | Useful only as a rollback |
| Update whose Backup.bin templates carry the 1:1 geometry | Yes | Yes, for the shot counter | Full update, Sony's files except the templates | Mechanism understood; high risk, needs the owner's decision (§4) |

## 1. What is reloaded after a resume and what is not

- `backup.ko` reloads Backup.bin from flash in its resume handler
  (`backup_resume` → `backupfile_load`). That is why the aspect setting
  survives a battery pull.
- Values computed at start-up (the shot-counter estimates, the menu tree) are
  part of the snapshot and are not recomputed ([aspect-ratio.md §10](aspect-ratio.md)).
- `backupfile_save()` in `backup.ko` calls the kernel's `wbi_drop()` before it
  writes Backup.bin. The kernel command line in the firmware sets
  `warm.ignore_drop=1` (`0800_appli/setting/kemco.txt`). This fits the camera:
  after Backup.bin writes and a battery pull it still resumes with `WARMBOOT`
  (LOG, 2026-11-09). Settings writes do not invalidate the snapshot on this
  body.
- `/sbin/init` reads `/setting/env.txt` and `/setting/mode/*`, but init only
  runs on a cold boot, before the snapshot is taken. These files do nothing
  after a resume.

## 2. No app can start itself at power-on

- Android is started once by `/sbin/init` (`/usr/bin/s_start_android.sh`,
  chrooted in `/android`) during the cold boot, so it is inside the snapshot.
- On power-off, `SyncAndroidService.Suspend()` (`framework/services.odex`)
  sends the ordered broadcast `com.android.server.SyncAndroidService.SUSPEND`.
  OpenMemories-Tweak listens to it to turn Wi-Fi off. libSyncAndroid then saves
  `/data/data` and `/data/system` to `/android/data/backup/bk1.bak`.
- On power-on, `SyncAndroidService.Resume()` sends **no** broadcast. It calls
  `AndroidSystemStateService.resume()` and, for `im_type == 8`,
  `syncAppsFromFilesystemToRam("/data/app /data/app-private")`. The string
  `...SyncAndroidService.RESUME` is only in the filter of the service's own
  test receiver, which only logs.
- No other power-on intent is defined in the framework or the system apps
  (searched every `.odex`: only the standard `BOOT_COMPLETED`, which is sent
  once at the cold boot, and media and package events).
- After a battery pull Android resumes from the snapshot, which was taken
  before our app existed. So an app can re-apply the fixes only when it is
  opened by hand, after each battery pull.
- Not verified: whether an app can write `im.elf` memory. The OpenMemories-Tweak
  README says its telnet daemon, started from the app, gives a root shell,
  which suggests apps run as root. On Linux 3.0, writing another process's
  memory through `/proc/<pid>/mem` needs a ptrace attach.

## 3. What a firmware update does with Backup.bin

Updater body scripts (`nflasha15 bin/udtrbody.bin`) and `backup.ko`, traced in
Ghidra and pinned in `a7r/firmup.py` and `tests/test_firmup.py`:

1. `startupdate.sh`: `ud_keep_backup.elf -p` saves the current Backup.bin.
2. `endupdate.sh` copies the update's template over `/setting/Backup.bin`
   and runs `ud_keep_backup.elf -r` (user settings kept) or `-u` (reset),
   chosen by `ud_get_uudtype.elf`.
3. `Backup_rewrite(mode)` (`-w` = 0, `-n` = 2, `-u` = 4, `-r` = 5) copies an
   old value into the template only if both values have the same size and the
   template's attribute allows it:
   - `attr & 0x74`: in modes 1 and 5;
   - `attr & 0x01`: in modes 4 and 5, or with the ID1 header flag set;
   - `attr & 0x02`: in every mode but 2.
4. `endupdate.sh` then erases `nflasha4` (MPR).

All 44 1:1 DATSZ and PXSZ properties are `attr 0` and zero in all 11 region
templates (`tests/test_firmware_integration.py`). Consequences:

- Any update, including a re-install of the official 3.20, resets the 1:1
  geometry in Backup.bin to zero. That makes it a complete rollback for our
  Backup.bin geometry writes. It is no route to persistence.
- The aspect setting (`0x01070012`, `attr 0x60`) is kept with `-r` and reset
  to 3:2 with `-u`.
- `python -m a7r.firmup <camera Backup.bin> <template>` lists every value an
  update would change.

## 4. The one route found that meets the criterion: a cold boot with 1:1 geometry in the template

The snapshot is rebuilt only after a cold boot, and on this body the only
stock cold boot found is the one after a firmware update. The shot counter's
1:1 estimates are computed at that boot from Backup.bin (`MprCtrl::Init`,
[aspect-ratio.md §10](aspect-ratio.md)). If the update's templates already
carry the 1:1 geometry, the new snapshot holds the right estimates, and a
battery pull no longer clears them.

Facts checked offline:

- `fwtool pack -c config.yaml -u updater.img -f firmware.tar` on the unmodified
  unpacked files reproduces Sony's `FirmwareData_ILCE7RV320.dat` byte for
  byte (205,553,816 bytes; also the decrypted FDAT). A build that changes only
  the templates would therefore differ from Sony's file only in the templates
  and `0111_backup_sum/backup.sum` (CRC-32 and size per file).
- The 11 templates are per region; `0110_backup/MainDest.txt` names
  `CX77900_UC2.bin` as the default. All 11 would carry the same change.
- The values to put there are the ones the camera already runs with
  (`a7r.formats.plan_square`). `CalcStillData_JPG` gives exactly the 1:1
  estimates that `a7r.mprphys` writes today.

Limits and unknowns:

- It is a firmware flash of every partition (with Sony's bytes except the
  templates): **high risk** under the project policy, needing a separate
  decision by the owner. It also needs a power source that cannot fail during
  the update.
- The Image Size patch is a code change in `libObj.so` and stays RAM-only. The
  Aspect Ratio menu still lists only 3:2 and 16:9.
- Same-version install: the camera's updater answers a guard check
  (`CHK_GUARD`, before any write) with statuses including `Invalid version`.
  Whether 3.20 over 3.20 is accepted is unknown.
- `config.xml` checks the backup CRC (`backup_sum`) after the partitions are
  written. A wrong sum would stop a half-done update; the recovery would be
  the official updater, as for any failed update.
- No public report found of a CXD90014 update repacked with only the templates
  changed, either successful or failed.

## 5. Other init-time values (not explored)

The Aspect Ratio item list comes from the UI model type `0x01070316` (`attr
0x01`, read-only, value 27 in the templates and on the camera;
[aspect-ratio.md §9](aspect-ratio.md)). It is read at start-up and is used
across many menus. Changing it would need its own study.

## Reproduce

```
.venv/bin/python -m pytest tests/test_firmup.py tests/test_firmware_integration.py -k "firmup or one_to_one or update_resets"
PYTHONPATH=fw/fwtool.py fw/pmca-venv/bin/python fw/fwtool.py/fwtool.py pack -c fw/out/config.yaml -u fw/out/updater.img -f fw/out/firmware.tar -o /tmp/repack
cmp /tmp/repack/firmware_packed.dat fw/FirmwareData_ILCE7RV320.dat
# Ghidra: backup.ko Backup_rewrite / FUN_000105e8 / backupfile_save; services.dex SyncAndroidService
```
