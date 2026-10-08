# Grocy for Rosie

This folder runs [Grocy](https://grocy.info), the pantry inventory behind Rosie's pantry
commands, as two Docker containers: Grocy itself and a nightly backup. How the pantry
works from Discord is in [`../docs/grocy-setup.md`](../docs/grocy-setup.md).

What's in git: this compose file, the Trader Joe's barcode plugin (`plugins/`), the backup
script and `.env.example`. Not in git: Grocy's data (`config/`), its backups (`backups/`)
and the per-machine `.env`.

## Start it

```
cd grocy
docker compose up -d
```

Open `http://<this machine>:9283`, log in as `admin` / `admin`, then:

1. **Change the password:** user menu, top right.
2. **Create an API key:** user menu → **Manage API keys** → **Add**.
3. **Add to Rosie's `.env`** (or `.env.dev`), then restart her:
   ```
   GROCY_URL=http://localhost:9283
   GROCY_API_KEY=...
   PANTRY_CHANNEL_ID=...      # a #pantry channel for plain-English updates
   PANTRY_LIST_NAME=Trader Joe's
   ```
4. Run **`/sync_tj_catalog`** once in Discord to load the Trader Joe's catalog.

Rosie creates the Fridge / Freezer / Pantry locations herself.

**Updating:** after a `git pull` that changes anything in this folder, run
`docker compose up -d` again. Grocy is pinned to version 4.7.1, the one the plugin was
tested on. To move to a newer Grocy, change the image tag in `docker-compose.yml`, run
`docker compose pull && docker compose up -d`, then scan a Trader Joe's item and run
`/in_stock` to check everything still works.

## Scanning Trader Joe's barcodes

`plugins/TraderJoesBarcodeLookupPlugin.php` handles unknown barcodes scanned in Grocy.
- **TJ's-brand items:** it fills in TJ's name, price, location and shelf life from
  Rosie's copy of the catalog. traderjoes.com blocks Grocy's own requests, so the plugin
  reads Rosie's database instead, read-only.
- **Everything else:** goes to Open Food Facts.
- **Where it looks:** this repo's `data/` folder and `rosies_recipe_box.db` by default.
  A different setup sets `ROSIE_DATA_DIR` / `ROSIE_DB_FILE` in `.env` (see `.env.example`).

Within 10 minutes of a scan, Rosie adds the TJ's photo and the other barcode lengths, and
asks in #pantry if the new product looks like a duplicate of an existing one.

## Phone app (camera scanning)

Phone browsers block the camera on plain `http://` pages, but the Grocy apps use the
phone's own camera code, so they work fine at home without HTTPS.

- **Android:** "Grocy: Grocery Management" by patzly (Google Play or F-Droid).
- **iPhone:** "Grocy Mobile" by Georg Meissner (App Store).

**To connect:**
1. In Grocy on a computer, go to the user menu → **Manage API keys** → **Add**. Each key
   has a QR code.
2. In the app, choose **Own server**.
3. Scan that QR code, or enter the server address and the key. At home the address is
   `http://<the server's local IP>:9283`.

New Trader Joe's items scanned in the app might be looked up by the app itself rather than
by the plugin. Either way, Rosie links them to TJ's within 10 minutes.

## Backups

The `grocy-backup` container backs Grocy up every night at 3:30am, and once whenever it
starts. Each backup goes in its own folder, `backups/grocy_<date>_<time>/`, with:
- `grocy.db`: the database (stock, products, history), copied safely while Grocy runs;
- `files.tar.gz`: product photos, the Trader Joe's plugin and `config.php`.

The newest 14 are kept. They live on the same disk as Grocy, so copy `backups/` somewhere
else now and then (another computer, a USB drive, cloud storage). `/pantry_status` in
Discord shows how old the newest one is. If Grocy runs from somewhere other than this
folder, set `GROCY_BACKUP_DIR` in Rosie's `.env` so she can find the backups.

**To restore one:**
```
docker compose stop grocy
cp backups/grocy_<date>_<time>/grocy.db config/data/grocy.db
tar -xzf backups/grocy_<date>_<time>/files.tar.gz -C config/data
docker compose start grocy
```
Rosie keeps her own nightly backups (`../data/backups/`). To roll back both sides, also
restore Rosie's backup from the same night, so her links to Grocy products line up.

## If Docker Desktop (Windows) won't start

An error like "listening on unix://…/sailor-ingest.sock … The file cannot be accessed by
the system" (or `docker-secrets-engine\engine.sock`) means a crash left a socket file that
Windows can't delete. A reboot does **not** fix it.

What works is to quit Docker Desktop, rename the folders that hold the sockets, and start
Docker again. Docker recreates both folders. In PowerShell:

```
Rename-Item "$env:LOCALAPPDATA\Docker\run" "run.stale-$(Get-Date -Format yyyyMMddHHmmss)"
Rename-Item "$env:LOCALAPPDATA\docker-secrets-engine" "docker-secrets-engine.stale-$(Get-Date -Format yyyyMMddHHmmss)"
```

The `*.stale-*` folders can't be deleted normally because of the socket file inside. They
take no space and can be left alone.
