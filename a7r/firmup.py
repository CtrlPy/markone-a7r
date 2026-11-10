"""Which Backup.bin values survive a firmware update (ILCE-7R 3.20, static analysis).

The updater body (nflasha15 bin/udtrbody.bin) handles Backup.bin like this:

1. startupdate.sh: `ud_keep_backup.elf -p` saves the current Backup.bin.
2. endupdate.sh: copies the update's factory template (0110_backup, one per
   region) over /setting/Backup.bin, then runs `ud_keep_backup.elf -r` (user
   settings kept) or `-u` (user settings reset), or `-w` for a factory update.
3. `ud_keep_backup.elf` calls `Backup_rewrite(mode)` in the backup.ko kernel
   module: -w = 0, -n = 2, -u = 4, -r = 5. For each property of the template,
   the old value is copied into the template when both have the same size and
   the template's attribute allows it (backup.ko FUN_000105e8, Ghidra):
   - attr & 0x74 (resettable user setting): in modes 1 and 5;
   - attr & 0x01 (read-only): in modes 4 and 5, or when the old data's ID1
     header flag is set;
   - attr & 0x02 (protected, e.g. factory adjustment): in every mode but 2.
   Everything else, including properties with attr 0, comes from the template.

Consequence: the DATSZ and PXSZ geometry (attr 0 in every 3.20 template, 1:1
slots zero) is reset to Sony's values by any update, even with the same
firmware. The aspect setting (attr 0x60) is kept only with `-r`.

    python -m a7r.firmup OLD_BACKUP TEMPLATE [--mode r]
"""
import argparse
import sys

MODES = {"w": 0, "n": 2, "u": 4, "r": 5}


def kept(attr, mode, id1=False):
    """True if Backup_rewrite(mode) keeps the old value of a property with this template attribute."""
    return bool(
        (attr & 0x74 and mode in (1, 5))
        or (attr & 0x01 and (id1 or mode in (4, 5)))
        or (attr & 0x02 and mode != 2)
    )


def merge(old, template, mode, id1=False):
    """Backup.bin values after an update: {pid: bytes}.

    old: {pid: bytes} from the camera; template: {pid: Property} from the update.
    """
    out = {}
    for pid, t in template.items():
        value = old.get(pid)
        keep = value is not None and len(value) == len(t.data) and kept(t.attr, mode, id1)
        out[pid] = value if keep else t.data
    return out


def main(argv=None):
    from a7r.backup import BackupFile
    from a7r.ids import IDS

    ap = argparse.ArgumentParser(prog="a7r.firmup", description=__doc__.splitlines()[0])
    ap.add_argument("old")
    ap.add_argument("template")
    ap.add_argument("--mode", choices=sorted(MODES), default="r")
    args = ap.parse_args(argv)
    old = {pid: p.data for pid, p in BackupFile(open(args.old, "rb").read()).properties.items()}
    template = BackupFile(open(args.template, "rb").read()).properties
    after = merge(old, template, MODES[args.mode])
    names = {v: k for k, v in IDS.items()}
    lost = sorted(pid for pid in after if pid in old and after[pid] != old[pid])
    print(f"{len(lost)} values would change with -{args.mode}:")
    for pid in lost:
        print(f"{pid:#010x} {names.get(pid, ''):40} {old[pid].hex()} -> {after[pid].hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
