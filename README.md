# AnuList

**Simple to shop with. Powerful when you need it.**

Self-hosted shared lists and recipes for Android, iPhone and desktop. AnuList is an installable web app (PWA) using a FastAPI backend and a durable SQLite database.

## Release 0.1

Implemented:
- Initial owner setup; distinct household accounts and one-use invitations
- Signed-in shared lists: shopping, general, travel, medication and takeaway
- Quick add, category grouping, one-tap completion, and completed section
- Saved household item defaults for quantity, category and shopping notes
- Bulk paste (one item per line), item editing, product photo upload
- Recipe storage and selection of ingredients to add to a shopping list
- Responsive mobile/desktop experience with Home Screen installation
- Updates between devices approximately every 6 seconds when online and app visible
- Persistent volume, verified database + image snapshot, offline restore utility
- CI tests and Docker build
- Tables for future retailer-specific products, matches and price observations

Not yet: automatic OneDrive setup, Google Home, live Woolworths/Coles pricing, recipe URL importer, AnyList data importer, offline writes, realtime push, password reset, push notifications. The shell can open offline but changes REQUIRE a connection and are never silently queued.

## Installation on AnuServer

Requirements: Docker Engine + Compose plugin, Git, and an HTTPS reverse proxy for use from phones. Use a directory separate from other projects.

    cd /opt/docker
    git clone https://github.com/Anubian-AU/AnuList.git anulist
    cd /opt/docker/anulist
    cp .env.example .env
    nano .env
    chmod +x scripts/*.sh
    ./scripts/deploy.sh

Container listens on loopback 127.0.0.1:8765 by default. It is NOT exposed to your network or Internet until you explicitly configure your reverse proxy. Keep COOKIE_SECURE=true behind HTTPS. Do not port-forward AnuList directly. Review authentication and TLS before remote exposure.

### Initial account

After the first successful deploy:

    docker compose exec anulist python bootstrap.py your@email.com

Choose a password when prompted (12+ characters). In the app, visit Household > Create invitation, share the code privately with your partner, and have them select I have a household invitation on the sign-in screen. Codes expire in 24 hours and can be used once.

### Install on a phone

Open the HTTPS website in Safari (iPhone) or Chrome (Android) and choose Add to Home Screen / Install app. The same site works from a desktop browser.

## Data safety

Live files in /opt/docker/anulist/data:
- anulist.db: SQLite database with WAL
- media/: private product images
- backups/: snapshots including BOTH database and images

Backup while the service runs:

    cd /opt/docker/anulist && ./scripts/backup.sh

The deploy script makes a consistent backup before updating an already-running instance, and stops if it finds a database but no running container.

### Restore a trusted snapshot

Stop the service first; restore replaces the entire dataset. The restore tool verifies checksums, validates database integrity, and makes a rollback snapshot first.

    cd /opt/docker/anulist
    docker compose stop anulist
    docker compose run --rm --no-deps -e ANULIST_RESTORE_CONFIRMED=YES anulist python /app/scripts/restore.py /data/backups/CHOSEN-FILENAME.zip
    docker compose up -d
    docker compose ps

Test backup AND restore on a disposable copy before entrusting important data to AnuList.

### Optional OneDrive backup

The current release produces local snapshot ZIP files. For off-site encrypted OneDrive storage, configure a host rclone OneDrive remote and a crypt remote such as anulist-crypt that writes encrypted files to OneDrive. Then:

    rclone copy /opt/docker/anulist/data/backups anulist-crypt:Backups --checksum

Keep OAuth tokens, encryption keys and scheduling settings outside Git. Configure a daily backup job followed by the encrypted upload; test download/decryption/restore and sensible retention. Automatic in-app OneDrive configuration is future work, not an implemented feature.

## Local development

Python 3.12:
- Create a virtual environment and install backend/requirements.txt.
- Set ANULIST_DB and ANULIST_MEDIA to local writable paths.
- Set COOKIE_SECURE=false only for trusted localhost HTTP development.
- From the backend directory run: uvicorn app:app --reload
- Visit http://127.0.0.1:8000

Tests from the repository root:

    PYTHONPATH=backend pytest -q backend/tests
    python -m compileall -q backend scripts
    node --check frontend/app.js

## Architecture and security

- One container with Python FastAPI, static web UI and SQLite WAL.
- Household scope enforced by every protected API query.
- Server-side opaque sessions are stored as hashes; Argon2id password hashes; CSRF checked on all authenticated writes.
- Secure HttpOnly cookies by default; image uploads re-encoded as JPEG after validation.
- Every shopping entry snapshots its saved defaults. Changing catalogue defaults does not rewrite old entries.
- Future Coles/Woolworths prices are separate per-retailer products with explicit date/source; no unsupported scraping.
- An initial version-1 schema is installed on startup. Future schema changes must use explicit numbered migrations and be tested with snapshots; never recreate production tables.
- Do not commit passwords, personal lists, backups or images to GitHub.

This is an initial working implementation awaiting actual deployment acceptance testing, not a security-audited public SaaS service. Keep network access private. See PROJECT_STATE.md and BACKLOG.md.
