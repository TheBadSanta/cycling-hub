#!/usr/bin/env python3
"""Extract daily health series from the full Apple Health XML (all years).

Series: weight (BodyMass), restingHR, VO2Max, HRV SDNN, sleep duration.
Daily aggregates (median of day's samples; sleep = sum of Asleep intervals
attributed to wake date). Output: /srv/data/physiology/features/health_daily.json
"""
import re, json, statistics
from pathlib import Path
from datetime import datetime, timedelta

XML = Path("/srv/data/physiology/TheSource/health/raw_xml/export.xml")
OUT = Path("/srv/data/physiology/features/health_daily.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

TYPES = {
    "HKQuantityTypeIdentifierBodyMass": "weight",
    "HKQuantityTypeIdentifierRestingHeartRate": "rhr",
    "HKQuantityTypeIdentifierVO2Max": "vo2max",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "sdnn",
}
REC = re.compile(r'type="(HKQuantityTypeIdentifier(?:BodyMass|RestingHeartRate|VO2Max|HeartRateVariabilitySDNN))".*?startDate="(\d{4}-\d{2}-\d{2}) (\d{2}):\d{2}:\d{2} [+-]\d{4}".*?value="([\d.]+)"')
SLEEP = re.compile(r'type="HKCategoryTypeIdentifierSleepAnalysis".*?startDate="(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):\d{2} [+-]\d{4}".*?endDate="(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):\d{2} [+-]\d{4}".*?value="HKCategoryValueSleepAnalysisAsleep')

daily = {}
sleep_by_wake = {}
n = 0
with XML.open("r", errors="ignore") as f:
    for line in f:
        if "SleepAnalysis" in line:
            m = SLEEP.search(line)
            if m:
                d1, h1, m1, d2, h2, m2 = m.groups()
                t1 = datetime.fromisoformat(f"{d1} {h1}:{m1}:00")
                t2 = datetime.fromisoformat(f"{d2} {h2}:{m2}:00")
                wake = d2 if int(h2) < 14 else (datetime.fromisoformat(d2) + timedelta(days=1)).date().isoformat()
                sleep_by_wake[wake] = sleep_by_wake.get(wake, 0) + max(0, (t2 - t1).total_seconds())
                n += 1
            continue
        if "HKQuantityTypeIdentifier" not in line:
            continue
        m = REC.search(line)
        if not m:
            continue
        typ, d, hh, val = m.groups()
        key = TYPES[typ]
        daily.setdefault(d, {}).setdefault(key, []).append(float(val))
        n += 1

out = {}
for d, kv in daily.items():
    out[d] = {k: round(statistics.median(v), 2) for k, v in kv.items()}
for wake, secs in sleep_by_wake.items():
    out.setdefault(wake, {})["sleep_s"] = int(min(secs, 14 * 3600))

OUT.write_text(json.dumps(out, indent=0, sort_keys=True))
years = {}
for d, kv in out.items():
    y = d[:4]
    for k in kv:
        years.setdefault(y, {}).setdefault(k, 0)
        years[y][k] += 1
print(f"records parsed: {n}, days: {len(out)}")
for y in sorted(years):
    print(y, years[y])
print("DONE")
