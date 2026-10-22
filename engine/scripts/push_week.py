#!/usr/bin/env python3
"""Push all structured workouts in a week-plan to the intervals.icu calendar.

Idempotent: before pushing a day, deletes existing WORKOUT events on that date
(so re-running updates rather than duplicates). Only pushes days with segments
(structured rides); walks/rest/empty skipped. By default pushes today + future
days only (past days already happened).

Usage:
  python3 push_week.py <week-plan.json>            # today + future
  python3 push_week.py <week-plan.json> --all      # every day incl past
"""
import sys, os, json, base64, urllib.request, urllib.error
from pathlib import Path
from datetime import date

for line in Path("/srv/_env/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

BASE = os.environ.get("INTERVALS_BASE_URL", "https://intervals.icu/api/v1")
auth = base64.b64encode(f"API_KEY:{os.environ['INTERVALS_API_KEY']}".encode()).decode()
HDR = {"Authorization": f"Basic {auth}", "User-Agent": "physiology-engine/0.3", "Content-Type": "application/json"}

def req(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, headers=HDR, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            b = resp.read()
            return resp.status, (json.loads(b) if b else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")

def zwo(day):
    parts = []
    for s in day["segments"]:
        if s[0] == "ss":
            parts.append(f'<SteadyState Duration="{s[1]}" Power="{s[2]/100:.2f}"/>')
        else:
            parts.append(f'<Ramp Duration="{s[1]}" PowerLow="{s[2]/100:.2f}" PowerHigh="{s[3]/100:.2f}"/>')
    body = "\n        ".join(parts)
    return (f"<workout_file>\n  <author>physiology-engine</author>\n  <name>{day['name']}</name>\n"
            f"  <description>{day.get('details','')}</description>\n  <sportType>bike</sportType>\n"
            f"  <workout>\n        {body}\n  </workout>\n</workout_file>")

plan = json.loads(Path(sys.argv[1]).read_text())
push_all = "--all" in sys.argv
today = date.today()
pushed, skipped, deleted = 0, 0, 0
for day in plan["days"]:
    d = day["date"]
    if not (day.get("segments")):        # only structured rides
        continue
    if not push_all and date.fromisoformat(d) < today:
        skipped += 1; continue
    # delete existing workout events on this date (idempotent)
    st, evs = req("GET", f"{BASE}/athlete/0/events?oldest={d}&newest={d}&category=WORKOUT")
    if isinstance(evs, list):
        for ev in evs:
            if (ev.get("start_date_local") or "")[:10] == d:
                req("DELETE", f"{BASE}/athlete/0/events/{ev['id']}"); deleted += 1
    # push
    payload = {"category": "WORKOUT", "start_date_local": f"{d}T00:00:00", "type": "Ride",
               "name": day["name"], "filename": "workout.zwo", "file_contents": zwo(day)}
    st, ev = req("POST", f"{BASE}/athlete/0/events", payload)
    if 200 <= st < 300:
        pushed += 1; print(f"  pushed {d}  {day['name']}")
    else:
        print(f"  FAIL {d}: {st} {str(ev)[:120]}")

print(f"\nweek {plan['week_start']}: pushed {pushed}, skipped-past {skipped}, replaced {deleted}")
