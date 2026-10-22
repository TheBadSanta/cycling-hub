#!/usr/bin/env bash
# Physiology engine daily pipeline (MP100). Fired by physio-daily.timer at 04:10.
# 1. Mirror live .fit inboxes from the NAS (Wahoo dropbox + TPV; GD chain is dead since Jun 10)
# 2. Pull original .fit files of new activities straight from intervals.icu (primary lane)
# 3. Consolidate new files into TheSource (dedup by fingerprint)
# 4. Snapshot intervals.icu wellness history
# 5. Mirror TheSource back to the NAS as the cold copy
set -uo pipefail

BASE=/srv/data/physiology
LOG=$BASE/logs/daily-$(date +%F).log
mkdir -p "$BASE/logs" "$BASE/sources"
exec >> "$LOG" 2>&1

echo "=== physio-daily $(date -Is) ==="

RS="rsync -a --rsync-path=/usr/bin/rsync"
NAS=$NAS_SSH
SCRIPTS=/srv/scrapers/physiology-engine/scripts

echo "--- pull NAS inboxes (redundant lane) ---"
$RS "$NAS:/volume1/Cycling/FitFileFaker/FITfiles/incoming_dropbox/"   "$BASE/sources/incoming_dropbox/"
# 2026-09-20 TPV lane retired (TPV syncs to intervals.icu directly; NAS folder archived)
# $RS "$NAS:/volume1/Cycling/FitFileFaker/FITfiles/incoming_tpvirtual/" "$BASE/sources/incoming_tpvirtual/"

echo "--- pull new fits from intervals.icu (primary lane) ---"
python3 "$SCRIPTS/pull_intervals_fits.py"

echo "--- consolidate ---"
python3 "$SCRIPTS/consolidate_fit_archive.py" --execute

echo "--- wellness ---"
python3 "$SCRIPTS/pull_wellness.py"

echo "--- training site (multi-week, navigable) ---"
# Full season site: overview + /current + /<block>/<n> per-week pages, plan vs
# executed + wellness. Published to NAS Web Station (YOUR-NAS-HOSTNAME/<hash>/).
python3 "$SCRIPTS/make_site.py" && \
  $RS --delete "$BASE/outbox/site/" "$NAS:/volume1/web/SITE_FOLDER/"

echo "--- mirror TheSource back to NAS (cold copy) ---"
$RS "$BASE/TheSource/" "$NAS:/volume1/Cycling/TheSource/"

echo "--- publish outbox to Google Drive (iPad access) ---"
# Anything the engine produces for Egor's eyes goes in outbox/ and lands in
# the GD app on the iPad. FTP-to-the-box is not an interface.
cp "$BASE/wellness/_pull_meta.json" "$BASE/outbox/" 2>/dev/null || true
rclone sync "$BASE/outbox/" "gdrive-personal:Training/physiology-engine/outbox/" --quiet

echo "--- mirror front-facing plan folder from Google Drive ---"
# The training plan + workout libraries live on GD (easycut) as the canonical
# front-facing copy; the engine keeps a read mirror for the adaptive-week job.
rclone sync "gdrive-personal:Training/AI training plan/" "$BASE/gd-mirror/AI training plan/" --quiet

# keep 30 days of logs
find "$BASE/logs" -name 'daily-*.log' -mtime +30 -delete

echo "=== done $(date -Is) ==="
