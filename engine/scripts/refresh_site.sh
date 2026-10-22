#!/usr/bin/env bash
# Lightweight intraday site refresh: pull fresh intervals data + rebuild + publish.
# Full pipeline (fit consolidation, wellness snapshot) stays at 04:10; this just
# keeps the dashboard current after a ride, without waiting for the daily run.
set -uo pipefail
python3 /srv/scrapers/physiology-engine/scripts/make_site.py \
  && rsync -a --delete --rsync-path=/usr/bin/rsync /srv/data/physiology/outbox/site/ $NAS_SSH:/volume1/web/SITE_FOLDER/
