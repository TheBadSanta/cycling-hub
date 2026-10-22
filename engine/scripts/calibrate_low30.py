#!/usr/bin/env python3
"""Calibrate lowest-30' sleeping HR against avgSleepingHR.

Streams the raw Apple Health export (HR samples ~3.5min apart at night), computes
per-night lowest 30-minute window mean (Garmin-style), joins with intervals.icu
avgSleepingHR for the same nights, saves the median offset for the weekly report.

Night = 23:00 (prev day) → 10:00, attributed to wake date. Window needs >=4 samples.
Output: low30_history.json (every night since 2010) + low30_calibration.json
"""
import re, json
from pathlib import Path
from datetime import datetime, timedelta

XML = Path("/srv/data/physiology/TheSource/health/raw_xml/export.xml")
WELLNESS = Path("/srv/data/physiology/wellness")
OUT = WELLNESS / "low30_calibration.json"
HIST = WELLNESS / "low30_history.json"

REC = re.compile(r'type="HKQuantityTypeIdentifierHeartRate".*?startDate="(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2}) ([+-]\d{4})".*?value="([\d.]+)"')

nights = {}  # wake_date -> [(epoch_s, bpm)]
kept = 0
with XML.open("r", errors="ignore") as f:
    for line in f:
        if "HeartRate" not in line:
            continue
        m = REC.search(line)
        if not m:
            continue
        d, hh, mm, ss, tz, val = m.groups()
        h = int(hh)
        if h >= 23:
            wake = (datetime.fromisoformat(d) + timedelta(days=1)).date().isoformat()
        elif h < 10:
            wake = d
        else:
            continue
        t = datetime.fromisoformat(f"{d} {hh}:{mm}:{ss}")
        nights.setdefault(wake, []).append((t.timestamp(), float(val)))
        kept += 1

print(f"night HR samples kept: {kept}, nights: {len(nights)}")

low30 = {}
for wake, samples in nights.items():
    samples.sort()
    best = None
    n = len(samples)
    for i in range(n):
        t0 = samples[i][0]
        win = [v for t, v in samples[i:] if t <= t0 + 1800]
        if len(win) >= 4:
            m = sum(win) / len(win)
            best = m if best is None else min(best, m)
    if best is not None:
        low30[wake] = round(best, 1)

HIST.write_text(json.dumps(low30, indent=0, sort_keys=True))
print(f"history saved: {len(low30)} nights -> {HIST}")

# join with wellness avgSleepingHR
avg = {}
for yf in WELLNESS.glob("20*.json"):
    for r in json.loads(yf.read_text()):
        if r.get("avgSleepingHR") is not None:
            avg[r["id"]] = r["avgSleepingHR"]

pairs = [(d, low30[d], avg[d]) for d in sorted(low30) if d in avg]
offsets = sorted(l - a for _, l, a in pairs)
if not pairs:
    raise SystemExit("no overlapping nights")
median = offsets[len(offsets) // 2]
import statistics
print(f"overlap nights: {len(pairs)}")
print(f"offset (low30 - avgSleepingHR): median {median:+.1f}, mean {statistics.mean(offsets):+.1f}, stdev {statistics.pstdev(offsets):.1f}")
print("sample:", pairs[-5:])

OUT.write_text(json.dumps({
    "median_offset": round(median, 1),
    "stdev": round(statistics.pstdev(offsets), 1),
    "n_nights": len(pairs),
    "period": [pairs[0][0], pairs[-1][0]],
    "note": "est_low30 = avgSleepingHR + median_offset",
}, indent=1))
print(f"saved {OUT}")
