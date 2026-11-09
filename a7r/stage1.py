"""Stage 1: write allow-listed Backup.bin properties through PMCA-RE updater mode.

Flow, all in one updater-mode session:
    1. read the full Backup.bin            -> OUTDIR/before.bin
    2. write each planned property (BKWR, the camera's own Backup_write)
    3. Backup_sync_all (BKSY), read each property back (BKRD) and compare
    4. read the full Backup.bin again       -> OUTDIR/after.bin
    5. report any property that changed other than the planned ones
       (known-noise ids such as counters and menu cursors are ignored)

Only ids in WRITABLE can be written, each with its allowed values. Bulk
Backup.bin writes (BKDW), file pushes and the interactive shell are refused.

    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.stage1 fw/Sony-PMCA-RE dumps/<name> --set 0x01070012=03
"""
import argparse
import datetime
import json
import struct
import sys
from pathlib import Path

from a7r.backup import BackupFile, diff
from a7r.ids import ASPECT_SETTING, IDS
from a7r.stage0 import _guard as _stage0_guard
from a7r.stage0 import check_backup, write_manifest

ALLOWED_REQUESTS = {"TEST", "BKRD", "BKWR", "BKSY", "BKDA", "EXIT"}

SENSOR_MAX = {"": (7360, 4912), "APSC_": (4800, 3200)}  # ILCE-7R 3:2 L, full frame / APS-C crop
JPEG_ESTIMATE_MAX = 65535  # largest 3:2 estimate on the camera is 36348


def _aspect_ok(data):
    return data in {bytes([v]) for v in range(4)}


def _pxsz_ok(limit):
    def check(data):
        w, h, n = struct.unpack("<HHI", data)
        if (w, h, n) == (0, 0, 0):
            return True  # rollback to the factory value
        return n == w * h and w == h and w % 16 == 0 and w <= limit[0] and h <= limit[1]
    return check


def _datsz_ok(data):
    return struct.unpack("<I", data)[0] <= JPEG_ESTIMATE_MAX


def _writable():
    table = {ASPECT_SETTING: (1, _aspect_ok)}  # 0=4:3, 1=3:2, 2=16:9, 3=1:1
    for name, pid in IDS.items():
        if "_1_1" not in name:
            continue
        if name.startswith("PXSZ"):
            prefix = "APSC_" if "_APSC_" in name else ""
            table[pid] = (8, _pxsz_ok(SENSOR_MAX[prefix]))
        else:
            table[pid] = (4, _datsz_ok)
    return table


# id -> (size, validator)
WRITABLE = _writable()

# Properties seen changing between reads with only the aspect menu touched
# (2026-11-09, ILCE-7R 3.20): counters, logs, menu cursor positions.
KNOWN_NOISE = {
    0x000D0027, 0x003C03A3, 0x00590013, 0x00930003, 0x00A10003,
    0x010708B9, 0x01070910, 0x01070AF9, 0x01070B74, 0x01070B75,
    0x01250005, 0x01850005,
}


def parse_change(text):
    pid, sep, value = text.partition("=")
    if not sep or not pid or not value:
        raise ValueError(f"expected ID=HEXBYTES, got {text!r}")
    return int(pid, 16), bytes.fromhex(value)


def plan(changes):
    planned = {}
    for pid, data in changes:
        if pid not in WRITABLE:
            raise ValueError(f"{pid:#010x} is not in the stage 1 allowlist")
        size, valid = WRITABLE[pid]
        if len(data) != size:
            raise ValueError(f"{pid:#010x}: size {len(data)}, expected {size}")
        if not valid(data):
            raise ValueError(f"{pid:#010x}: value {data.hex()} not allowed")
        planned[pid] = data
    return planned


def unexpected_changes(before, after, planned, noise=KNOWN_NOISE):
    a, b = BackupFile(before), BackupFile(after)
    found = []
    for pid, old, new in diff(a, b):
        if pid in planned and new == planned[pid]:
            continue
        if pid in noise and pid not in planned:
            continue
        found.append((pid, old, new))
    for pid, data in planned.items():
        if b.properties[pid].data != data and all(pid != f[0] for f in found):
            found.append((pid, a.properties[pid].data, b.properties[pid].data))
    return found


def _guard(backend):
    return _stage0_guard(backend, ALLOWED_REQUESTS)


def run(pmca_root, outdir, planned, expected_model):
    sys.path.insert(0, str(pmca_root))
    from pmca.commands.usb import updaterShellCommand
    from pmca.platform.backend.usb import UsbPlatformBackend

    outdir.mkdir(parents=True, exist_ok=False)
    report = {}

    def complete(device):
        backend = _guard(UsbPlatformBackend(device))
        backend.start()
        try:
            before = backend.getBackupData()
            (outdir / "before.bin").write_bytes(before)
            check_backup(before, expected_model)
            old = {pid: backend.readBackup(pid) for pid in planned}
            for pid, data in planned.items():
                print(f"Writing {pid:#010x}: {old[pid].hex()} -> {data.hex()}")
                backend.writeBackup(pid, data)
            backend.syncBackup()
            readback = {pid: backend.readBackup(pid) for pid in planned}
            after = backend.getBackupData()
            (outdir / "after.bin").write_bytes(after)
            check_backup(after, expected_model)
            report["old"] = {f"{k:#010x}": v.hex() for k, v in old.items()}
            report["readback"] = {f"{k:#010x}": v.hex() for k, v in readback.items()}
            report["readback_ok"] = all(readback[k] == v for k, v in planned.items())
            report["unexpected"] = [
                (f"{p:#010x}", o.hex() if o else None, n.hex() if n else None)
                for p, o, n in unexpected_changes(before, after, planned)]
        finally:
            backend.stop()

    updaterShellCommand(complete=complete)
    if "readback_ok" not in report:
        raise SystemExit("Write session did not complete; check the camera and the output above.")
    meta = {"date": datetime.datetime.now().isoformat(timespec="seconds"),
            "planned": {f"{k:#010x}": v.hex() for k, v in planned.items()}, **report}
    write_manifest(outdir, meta)
    print(json.dumps(meta, indent=2))
    if not report["readback_ok"] or report["unexpected"]:
        raise SystemExit("Write finished with differences, see above. Restore: re-run with the old values.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.stage1", description="Write allow-listed Backup.bin properties")
    ap.add_argument("pmca_root", type=Path)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--set", dest="changes", action="append", default=[], type=parse_change,
                    help="ID=HEXBYTES, e.g. 0x01070012=03")
    ap.add_argument("--plan-file", type=Path, help="JSON {id: hexbytes} from python -m a7r.formats")
    ap.add_argument("--model", default="ILCE-7R")
    args = ap.parse_args(argv)
    changes = list(args.changes)
    if args.plan_file:
        changes += [(int(k, 16), bytes.fromhex(v)) for k, v in json.loads(args.plan_file.read_text()).items()]
    if not changes:
        ap.error("nothing to write: give --set or --plan-file")
    run(args.pmca_root, args.outdir, plan(changes), args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
