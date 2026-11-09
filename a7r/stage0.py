"""Stage 0: read-only backup of a camera through Sony-PMCA-RE updater mode.

Boots the camera into PMCA-RE's updater shell (the installed firmware is not
modified), then uses only read requests to save:

    Backup.bin         full settings store (USB request BKDA)
    backup_status.bin  backup status block (BKST)
    nflasha.bin        whole NAND block device (PULL /dev/nflasha)

and writes MANIFEST.json + SHA256SUMS. Every USB shell request goes through a
guard that refuses anything outside ALLOWED_REQUESTS, so no write request
(BKWR, BKDW, PUSH, ...) can be sent from this script.

Run with the PMCA-RE interpreter and this repo on the path:
    PYTHONPATH=. fw/pmca-venv/bin/python -m a7r.stage0 fw/Sony-PMCA-RE dumps/2026-11-09
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

from a7r.backup import BackupError, BackupFile

ALLOWED_REQUESTS = {"TEST", "BKST", "BKDA", "PULL", "EXIT"}
MODEL_NAME_ID = 0x003E0005
MANIFEST_FILES = {"MANIFEST.json", "SHA256SUMS"}


def check_backup(data: bytes, expected_model: str) -> dict:
    try:
        bk = BackupFile(data)
    except BackupError as e:
        raise ValueError(f"Backup.bin is not valid: {e}") from e
    prop = bk.properties.get(MODEL_NAME_ID)
    model = prop.data.split(b"\0", 1)[0].decode("latin1") if prop else ""
    if model != expected_model:
        raise ValueError(f"Backup.bin belongs to {model or 'unknown model'}, expected {expected_model}")
    return {"model": model, "region": bk.region, "version": bk.version,
            "revision": bk.revision, "properties": len(bk.properties)}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(outdir: Path, meta: dict) -> dict:
    outdir = Path(outdir)
    files = {}
    for p in sorted(outdir.iterdir()):
        if p.is_file() and p.name not in MANIFEST_FILES:
            files[p.name] = {"size": p.stat().st_size, "sha256": _sha256(p)}
    manifest = {"meta": meta, "files": files}
    (outdir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (outdir / "SHA256SUMS").write_text("".join(f"{v['sha256']}  {k}\n" for k, v in files.items()))
    return manifest


def _guard(backend):
    original = backend._req

    def guarded(cmd, *args, **kwargs):
        name = cmd.decode("latin1")
        if name not in ALLOWED_REQUESTS:
            raise PermissionError(f"stage0 refuses USB shell request {name}")
        return original(cmd, *args, **kwargs)

    backend._req = guarded
    return backend


def run(pmca_root: Path, outdir: Path, flash_path: str, expected_model: str):
    sys.path.insert(0, str(pmca_root))
    from pmca.commands.usb import updaterShellCommand
    from pmca.platform.backend.usb import UsbPlatformBackend

    outdir.mkdir(parents=True, exist_ok=False)
    result = {}

    def complete(device):
        backend = _guard(UsbPlatformBackend(device))
        backend.start()
        try:
            print("Reading backup status (BKST)")
            (outdir / "backup_status.bin").write_bytes(backend.getBackupStatus())
            print("Reading Backup.bin (BKDA)")
            data = backend.getBackupData()
            (outdir / "Backup.bin").write_bytes(data)
            result["backup"] = check_backup(data, expected_model)
            print(f"Backup.bin OK: {result['backup']}")
            if flash_path:
                print(f"Reading {flash_path} (PULL), this takes a while")
                with (outdir / "nflasha.bin").open("wb") as f:
                    backend.readFile(flash_path, f, lambda size: print(f"  size {size} bytes"))
        finally:
            backend.stop()

    updaterShellCommand(complete=complete)
    if "backup" not in result:
        raise SystemExit("Backup was not read; nothing verified. See the output above.")
    meta = {"date": datetime.datetime.now().isoformat(timespec="seconds"),
            "flash_path": flash_path, **result["backup"]}
    manifest = write_manifest(outdir, meta)
    for name, info in manifest["files"].items():
        print(f"{info['sha256']}  {info['size']:>12}  {name}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="a7r.stage0", description="Read-only camera backup via PMCA-RE")
    ap.add_argument("pmca_root", type=Path, help="Sony-PMCA-RE checkout")
    ap.add_argument("outdir", type=Path, help="new directory for the dump, e.g. dumps/2026-11-09")
    ap.add_argument("--flash", default="/dev/nflasha", help="block device to pull; '' to skip")
    ap.add_argument("--model", default="ILCE-7R")
    args = ap.parse_args(argv)
    run(args.pmca_root, args.outdir, args.flash, args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
