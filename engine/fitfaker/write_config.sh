#!/bin/bash
# Build fit-file-faker's config from /srv/_env/.env at service start (secrets live only in .env). 2026-10-03
set -e; source <(grep -E "^(GARMIN_USERNAME|GARMIN_PASSWORD)=" /srv/_env/.env | sed 's/^\([A-Z_]*\)=\(.*\)$/\1="\2"/')
C=/srv/scrapers/fitfaker/.config/FitFileFaker; mkdir -p "$C"; umask 077
printf '{\n  "garmin_username": "%s",\n  "garmin_password": "%s",\n  "fitfiles_path": "/srv/data/physiology/fitfaker/inbox"\n}\n' "$GARMIN_USERNAME" "$GARMIN_PASSWORD" > "$C/.config.json"
