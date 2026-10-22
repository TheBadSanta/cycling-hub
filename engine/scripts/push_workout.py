#!/usr/bin/env python3
"""Push a planned workout from a week-plan JSON to the intervals.icu calendar.

Converts the day's segments to .zwo (native <Ramp> — pure ramps, no steps) and
POSTs a WORKOUT event. intervals.icu then syncs it to the Wahoo head unit.

Usage: push_workout.py <week-plan.json> <day-index 0..6> <target-date YYYY-MM-DD>
"""
import sys, os, json, base64, urllib.request, urllib.error
from pathlib import Path

for line in Path("/srv/_env/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

plan_path, day_idx, target = sys.argv[1], int(sys.argv[2]), sys.argv[3]
day = json.loads(Path(plan_path).read_text())["days"][day_idx]

def zwo(day):
    parts = []
    for s in day["segments"]:
        if s[0] == "ss":
            parts.append(f'<SteadyState Duration="{s[1]}" Power="{s[2]/100:.2f}"/>')
        else:
            parts.append(f'<Ramp Duration="{s[1]}" PowerLow="{s[2]/100:.2f}" PowerHigh="{s[3]/100:.2f}"/>')
    body = "\n        ".join(parts)
    return f"""<workout_file>
    <author>physiology-engine</author>
    <name>{day['name']}</name>
    <description>{day['details']}</description>
    <sportType>bike</sportType>
    <workout>
        {body}
    </workout>
</workout_file>"""

xml = zwo(day)
auth = base64.b64encode(f"API_KEY:{os.environ['INTERVALS_API_KEY']}".encode()).decode()
BASE = os.environ.get('INTERVALS_BASE_URL', 'https://intervals.icu/api/v1'); HDR = {"Authorization": f"Basic {auth}", "User-Agent": "physiology-engine/0.2"}
# idempotent (2026-10-01): remove existing UNPAIRED workout events on the target date first — re-pushing a day
# used to stack duplicates (Sun 4 Oct had three). A workout already paired to a ride is left alone.
try:
    old_ev = json.loads(urllib.request.urlopen(urllib.request.Request(f"{BASE}/athlete/0/events?oldest={target}&newest={target}", headers=HDR), timeout=30).read())
    for ev in old_ev:
        if ev.get("category") == "WORKOUT" and not ev.get("paired_activity_id"):
            urllib.request.urlopen(urllib.request.Request(f"{BASE}/athlete/0/events/{ev['id']}", headers=HDR, method="DELETE"), timeout=30)
            print(f"replaced old workout event {ev['id']} ({ev.get('name')})")
except Exception as e: print("warning: could not clear old events:", e)
payload = {
    "category": "WORKOUT",
    "start_date_local": f"{target}T00:00:00",
    "type": "Ride",
    "name": day["name"],
    "filename": "workout.zwo",
    "file_contents": xml,
}
req = urllib.request.Request(
    f"{os.environ.get('INTERVALS_BASE_URL','https://intervals.icu/api/v1')}/athlete/0/events",
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"Basic {auth}", "User-Agent": "physiology-engine/0.2",
             "Content-Type": "application/json"},
    method="POST")
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        ev = json.loads(r.read())
    print(f"pushed: event id {ev.get('id')} | {ev.get('name')} | {ev.get('start_date_local')}")
    print(f"  moving_time={ev.get('moving_time')}s  load={ev.get('icu_training_load')}  if={ev.get('icu_intensity')}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()[:500]}")
    sys.exit(1)
