# AnuList project state

Updated 2026-10-08. Release 0.1.0: first implementation; server deployment and mobile acceptance pending.

## Purpose
Self-hosted shared household lists and recipes. Normal phone workflow is quick-add then one-tap completion. Advanced options stay out of the primary path.

## Architecture
- Python 3.12 / FastAPI, SQLite WAL, schema version 1.
- Vanilla JavaScript/CSS mobile-first PWA and service worker.
- Argon2id account passwords; hashed opaque sessions; session-bound CSRF protection.
- Household membership and one-use invitation codes.
- Single Docker Compose service on loopback port 8765; external TLS proxy required for phones.
- Persistent bind mount: database, private images and local backup ZIPs.
- Database snapshot + image archive with SHA256 manifest; optional separately configured encrypted rclone OneDrive backup.

## Implemented
Household auth and invites; lists and entries; completion, category, bulk paste; household catalogue defaults; JPEG photo uploads and private serving; recipes CRUD and ingredients-to-list; phone and desktop UI; polling sync; backups; initial restore tool; CI and pytest integration tests; retailer/price tables (not populated).

## Important decisions
- Start with one app service. Do not build a second business-logic implementation.
- Use SQLite for a small household. Introduce explicit migrations before version 2.
- Historic entries keep snapshot data. Catalog default changes apply to new entries.
- v0.1 PWA shell is offline-cached; writes are intentionally online-only until an outbox/conflict protocol exists.
- No scraped retailer prices, unverified grocery claims, or Google Home promises.
- Default deployment not publicly exposed; Secure cookies require HTTPS.

## Known issues / limitations
- GitHub CI and Docker smoke check required after the first commits.
- Production deployment, iPhone/Android real-device tests, and restore-on-disposable-copy not yet confirmed.
- No password reset, account transfer or member removal UI.
- Offline edits and push notifications not implemented.
- Home integration, importing AnyList data, recipe URL scraping, weekly supermarket basket comparison remain future milestones.
- OneDrive crypt rclone integration is documented but NOT automated.
- Private network only until authentication / TLS / backups are verified.

## Next
1. CI green and Docker smoke.
2. Deploy to /opt/docker/anulist behind HTTPS; create owner and invite partner.
3. Confirm Android and iOS shopping, notes/photos, recipes, shared updates.
4. Test backup and restore against disposable instance; configure OneDrive crypt uploads.
5. Mobile UI fixes, then migration framework and offline conflict-safe writes.
