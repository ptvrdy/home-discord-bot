#!/bin/sh
# Nightly Grocy backup, run by the grocy-backup container (see docker-compose.yml).
# Each backup is a folder backups/grocy_<timestamp>/ holding:
#   grocy.db         - a consistent copy of the database (safe while Grocy runs)
#   files.tar.gz     - product photos, the TJ's plugin, and config.php
# The newest 14 are kept.
set -e

stamp=$(date +%Y%m%d_%H%M%S)
dest="/backups/grocy_$stamp"
mkdir -p "$dest"

sqlite3 /config/data/grocy.db ".backup '$dest/grocy.db'"
tar -czf "$dest/files.tar.gz" -C /config/data storage plugins config.php

ls -1d /backups/grocy_* | sort -r | tail -n +15 | xargs -r rm -rf
echo "Grocy backed up to $dest"
