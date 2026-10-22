#!/usr/bin/env python3
"""Snapshot intervals.icu wellness (the physiology hub) to local JSON, per year.

intervals.icu is fed daily by IntervalsCompanion on Egor's iPhone (HRV rMSSD+SDNN,
RHR, sleep, readiness, SpO2, Baevsky SI, respiration, steps, weight, sporadic VO2max).
This pulls the WHOLE history every run — payload is a few MB, so no watermark logic.

Output: /srv/data/physiology/wellness/{YYYY}.json  (one array per year)
        /srv/data/physiology/wellness/_pull_meta.json

Env: INTERVALS_API_KEY / INTERVALS_BASE_URL from /srv/_env/.env
"""
import os, json, base64, urllib.request
from pathlib import Path
from datetime import date, datetime, timezone

for line in Path("/srv/_env/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ["INTERVALS_API_KEY"]
BASE = os.environ.get("INTERVALS_BASE_URL", "https://intervals.icu/api/v1")
OUT = Path("/srv/data/physiology/wellness")
OUT.mkdir(parents=True, exist_ok=True)

auth = base64.b64encode(f"API_KEY:{API_KEY}".encode()).decode()
url = f"{BASE}/athlete/0/wellness?oldest=2010-01-01&newest={date.today().isoformat()}"
req = urllib.request.Request(url, headers={
    "Authorization": f"Basic {auth}",
    "User-Agent": "physiology-engine/0.2 (mp100)",
})
with urllib.request.urlopen(req, timeout=60) as resp:
    rows = json.loads(resp.read())

by_year = {}
for r in rows:
    by_year.setdefault(r["id"][:4], []).append(r)

for yyyy, yrows in sorted(by_year.items()):
    (OUT / f"{yyyy}.json").write_text(json.dumps(yrows, indent=1))

meta = {
    "pulled_at": datetime.now(timezone.utc).isoformat(),
    "total_days": len(rows),
    "years": {y: len(v) for y, v in sorted(by_year.items())},
    "latest_day": rows[-1]["id"] if rows else None,
}
(OUT / "_pull_meta.json").write_text(json.dumps(meta, indent=2))
print(f"Wellness: {len(rows)} days, latest {meta['latest_day']}, years: {meta['years']}")
