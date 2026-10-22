#!/usr/bin/env python3
"""Download original .fit files of new activities from intervals.icu into the sources inbox.

Why: every workout reaches intervals.icu (Wahoo direct integration, HealthFit for AWU
walks). Pulling from the API removes the dependency on the fragile GD/Dropbox → NAS
Cloud Sync chains. Downloads land in sources/icu_downloads/ and the consolidator
fingerprint-dedups them against files that also arrived via the Wahoo/TPV inboxes.

State: /srv/data/physiology/TheSource/icu_pull_state.json  (per-activity outcome)
Lookback: 14 days before the newest previously-pulled activity (catches late uploads).
Manual activities (no file, e.g. backfilled walks) are recorded as "no_file" and skipped.
"""
import os, json, base64, urllib.request, urllib.error
from pathlib import Path
from datetime import date, timedelta

for line in Path("/srv/_env/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ["INTERVALS_API_KEY"]
BASE = os.environ.get("INTERVALS_BASE_URL", "https://intervals.icu/api/v1")
OUT = Path("/srv/data/physiology/sources/icu_downloads")
STATE_PATH = Path("/srv/data/physiology/TheSource/icu_pull_state.json")
OUT.mkdir(parents=True, exist_ok=True)

HDR = {
    "Authorization": "Basic " + base64.b64encode(f"API_KEY:{API_KEY}".encode()).decode(),
    "User-Agent": "physiology-engine/0.2 (mp100)",
}

def get(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {"activities": {}, "newest_date": "2026-05-20"}

oldest = (date.fromisoformat(state["newest_date"][:10]) - timedelta(days=14)).isoformat()
acts = json.loads(get(f"{BASE}/athlete/0/activities?oldest={oldest}&newest={(date.today() + timedelta(days=1)).isoformat()}"))
print(f"{len(acts)} activities since {oldest}")

new, no_file, errors = 0, 0, 0
for a in acts:
    aid = a["id"]
    if aid in state["activities"]:
        continue
    start = (a.get("start_date_local") or "")[:19].replace(":", "").replace("T", "_")
    try:
        raw = get(f"{BASE}/activity/{aid}/file")
        # gzip if intervals returns .fit.gz content
        if raw[:2] == b"\x1f\x8b":
            import gzip
            raw = gzip.decompress(raw)
        fname = f"{start}_{a.get('type','X')}_{aid}.fit"
        (OUT / fname).write_bytes(raw)
        state["activities"][aid] = {"status": "downloaded", "file": fname}
        new += 1
    except urllib.error.HTTPError as e:
        if e.code in (404, 422):
            state["activities"][aid] = {"status": "no_file"}
            no_file += 1
        else:
            print(f"  ERROR {aid}: HTTP {e.code}")
            errors += 1
    d = (a.get("start_date_local") or "")[:10]
    if d > state["newest_date"]:
        state["newest_date"] = d

STATE_PATH.write_text(json.dumps(state, indent=1))
print(f"Downloaded: {new}, no-file (manual): {no_file}, errors: {errors}, watermark: {state['newest_date']}")
