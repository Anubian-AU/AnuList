"""OFFLINE restore. Stop application before invoking. Makes a rollback snapshot."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile
from storage import DB_PATH, MEDIA_PATH
from backup import backup

def sha_file(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda:f.read(1024*1024),b""):
            h.update(buf)
    return h.hexdigest()

def restore(archive_name):
    if os.environ.get("ANULIST_RESTORE_CONFIRMED") != "YES":
        raise SystemExit("Refusing restore. Stop the service and set ANULIST_RESTORE_CONFIRMED=YES")
    path=Path(archive_name)
    if not path.is_file():
        raise SystemExit("Archive not found")
    with tempfile.TemporaryDirectory(dir=DB_PATH.parent) as scratch:
        temp=Path(scratch)
        with ZipFile(path) as archive:
            if archive.testzip():
                raise SystemExit("Corrupt ZIP archive")
            manifest=json.loads(archive.read("manifest.json"))
            if manifest.get("format") != 1 or "database.sqlite3" not in manifest.get("files",{}):
                raise SystemExit("Unsupported backup format")
            expected=set(manifest["files"])
            if set(archive.namelist()) != expected | {"manifest.json"}:
                raise SystemExit("Archive file list mismatch")
            for name, digest in manifest["files"].items():
                if name != "database.sqlite3" and not re.fullmatch(r"media/[0-9a-f-]{36}\.jpg",name):
                    raise SystemExit("Unsafe archive path")
                target=temp/name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("wb") as dest:
                    shutil.copyfileobj(source,dest)
                if sha_file(target)!=digest:
                    raise SystemExit("Backup checksum mismatch")
        test=sqlite3.connect(str(temp/"database.sqlite3"))
        try:
            if test.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise SystemExit("Backup database failed integrity check")
        finally:
            test.close()
        if DB_PATH.exists():
            backup()
        old_media=MEDIA_PATH.with_name(MEDIA_PATH.name+".before-restore")
        if old_media.exists():
            raise SystemExit("Previous restore staging folder exists; resolve it first")
        if MEDIA_PATH.exists():
            MEDIA_PATH.rename(old_media)
        (temp/"media").mkdir(exist_ok=True)
        shutil.move(str(temp/"media"),str(MEDIA_PATH))
        os.replace(temp/"database.sqlite3",DB_PATH)
        for suffix in ("-wal","-shm"):
            (Path(str(DB_PATH)+suffix)).unlink(missing_ok=True)
        if old_media.exists():
            shutil.rmtree(old_media)
    print("Restore complete. Start AnuList and verify household lists.")

if __name__ == "__main__":
    if len(sys.argv)!=2:raise SystemExit("Usage: python /app/scripts/restore.py /data/backups/anulist-DATE.zip")
    restore(sys.argv[1])
