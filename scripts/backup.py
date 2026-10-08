"""Consistent SQLite + media snapshot. Use on a running instance."""
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from storage import DB_PATH, MEDIA_PATH

def hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def backup(outdir=None):
    outdir = Path(outdir or DB_PATH.parent / "backups")
    outdir.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.is_file():
        raise SystemExit("Database file missing. Initialise AnuList first.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = outdir / ("anulist-" + stamp + ".zip")
    os.umask(0o077)
    with tempfile.TemporaryDirectory() as work:
        snapshot = Path(work) / "database.sqlite3"
        source = sqlite3.connect(str(DB_PATH))
        dest = sqlite3.connect(str(snapshot))
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        check = sqlite3.connect(str(snapshot))
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("Database integrity check failed")
        finally:
            check.close()
        manifest = {"format": 1, "created_utc": stamp, "files": {}}
        temp_zip = filename.with_suffix(".zip.tmp")
        try:
            with ZipFile(temp_zip, "w", ZIP_DEFLATED, compresslevel=6) as archive:
                manifest["files"]["database.sqlite3"] = hash_file(snapshot)
                archive.write(snapshot, "database.sqlite3")
                for path in MEDIA_PATH.glob("*.jpg"):
                    if not path.is_file():
                        continue
                    name = "media/" + path.name
                    manifest["files"][name] = hash_file(path)
                    archive.write(path, name)
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            os.replace(temp_zip, filename)
        finally:
            temp_zip.unlink(missing_ok=True)
    print("Backup complete:", filename)
    return filename

if __name__ == "__main__":
    backup()
