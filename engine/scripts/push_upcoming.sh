#!/usr/bin/env bash
# Fired Friday morning: push the WHOLE upcoming week (next Monday's plan) to the
# intervals.icu calendar so Egor sees next week ahead. Idempotent (push_week deletes
# existing WORKOUT events per day before pushing).
set -uo pipefail
NEXTMON=$(python3 -c 'from datetime import date,timedelta; d=date.today(); print((d+timedelta(days=(7-d.weekday())%7 or 7)).isoformat())')
PLAN="/srv/data/physiology/plans/week-${NEXTMON}.json"
if [ -f "$PLAN" ]; then
  echo "pushing upcoming week ${NEXTMON}"
  python3 /srv/scrapers/physiology-engine/scripts/push_week.py "$PLAN" --all
else
  echo "no plan for upcoming week ${NEXTMON} (nothing to push)"
fi
