import os
import sqlite3
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager

DB_PATH = Path(os.environ.get("ANULIST_DB", "/data/anulist.db"))
MEDIA_PATH = Path(os.environ.get("ANULIST_MEDIA", "/data/media"))

def uid():
    return str(uuid4())

def connect():
    db = sqlite3.connect(str(DB_PATH), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=20000")
    return db

@contextmanager
def transaction():
    db = connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_PATH.mkdir(parents=True, exist_ok=True)
    with transaction() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 password_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS households(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members(
 user_id TEXT NOT NULL REFERENCES users(id), household_id TEXT NOT NULL REFERENCES households(id),
 role TEXT NOT NULL CHECK(role IN ('owner','member')), PRIMARY KEY(user_id,household_id));
CREATE TABLE IF NOT EXISTS sessions(
 token_hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id),
 expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invitations(
 code_hash TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
 expires_at TEXT NOT NULL, used_at TEXT);
CREATE TABLE IF NOT EXISTS lists(
 id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
 name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'general',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS catalogue(
 id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
 name TEXT NOT NULL, quantity TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT '', image_key TEXT,
 UNIQUE(household_id,name COLLATE NOCASE));
CREATE TABLE IF NOT EXISTS entries(
 id TEXT PRIMARY KEY, list_id TEXT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
 catalogue_id TEXT REFERENCES catalogue(id) ON DELETE SET NULL,
 name TEXT NOT NULL, quantity TEXT NOT NULL DEFAULT '',
 note TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
 checked INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,
 added_by TEXT REFERENCES users(id), checked_by TEXT REFERENCES users(id),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_entries_list ON entries(list_id);
CREATE TABLE IF NOT EXISTS recipes(
 id TEXT PRIMARY KEY, household_id TEXT NOT NULL REFERENCES households(id),
 title TEXT NOT NULL, servings INTEGER NOT NULL DEFAULT 4,
 instructions TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ingredients(
 id TEXT PRIMARY KEY, recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
 name TEXT NOT NULL, quantity TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS retailers(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS retailer_products(
 id TEXT PRIMARY KEY, retailer_id TEXT NOT NULL REFERENCES retailers(id),
 external_id TEXT NOT NULL, title TEXT NOT NULL, barcode TEXT, pack_size TEXT,
 UNIQUE(retailer_id,external_id));
CREATE TABLE IF NOT EXISTS product_matches(
 catalogue_id TEXT NOT NULL REFERENCES catalogue(id), product_id TEXT NOT NULL REFERENCES retailer_products(id),
 approved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(catalogue_id,product_id));
CREATE TABLE IF NOT EXISTS price_observations(
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES retailer_products(id),
 price_cents INTEGER NOT NULL, observed_at TEXT NOT NULL, region TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL, promotion TEXT NOT NULL DEFAULT '', valid_until TEXT);
PRAGMA user_version=1;
""")
    if os.name != "nt":
        os.chmod(DB_PATH.parent, 0o750)
