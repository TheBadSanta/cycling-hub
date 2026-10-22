#!/usr/bin/env python3
"""Pull Health Auto Export JSONs (iPhone -> personal Google Drive, daily 10:30) and compute the true
lowest-30' sleeping HR per night, same algorithm as calibrate_low30.py (night = 23:00 prev day -> 10:00,
30-min rolling window, >=4 samples, min window mean). Appends/overwrites wellness/low30_history.json.
Runs before the 11:15 watchman (ExecStartPre) and can be run by hand:  --dry = compute, don't write."""
import json, sys, subprocess, shutil, re
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

DRY = "--dry" in sys.argv
ROOT = Path("/srv/data/physiology"); SRC = ROOT / "sources/health_auto_export"; HIST = ROOT / "wellness/low30_history.json"
FOLDER_ID = "YOUR_DRIVE_FOLDER_ID"      # Health Auto Export ROOT folder on gdrive-personal (recursive: HealthExport/ + Shortcut saves)
SRC.mkdir(parents=True, exist_ok=True)
r = subprocess.run(["rclone", "copy", "gdrive-personal:", str(SRC), "--drive-root-folder-id", FOLDER_ID, "--include", "*.json", "--quiet"],
                   capture_output=True, text=True, timeout=300)
if r.returncode: print("rclone:", r.stderr[:200])
# Lane 2: Shortcut "Save File" -> Dropbox /HealthExport -> NAS Cloud Sync -> /volume1/Cycling/HealthExport -> here (rsync, ignore if absent)
NAS_DBX = "$NAS_SSH:/volume1/Cycling/HealthExport/"; (SRC / "dropbox").mkdir(exist_ok=True)
r2 = subprocess.run(["rsync", "-a", "--rsync-path=/usr/bin/rsync", "--include=*.json", "--include=*/", "--exclude=*", NAS_DBX, str(SRC / "dropbox/")],
                    capture_output=True, text=True, timeout=120)
if r2.returncode and "No such file" not in r2.stderr: print("rsync NAS HealthExport:", r2.stderr[:160])

samples = {}   # ts -> bpm (dedupe across files)
for f in sorted(SRC.rglob("*.json")):          # app automation files AND Shortcut-saved files, any name
    try: d = json.load(open(f))
    except Exception as e: print("bad file", f.name, e); continue
    for m in d.get("data", {}).get("metrics", []):
        if m.get("name") != "heart_rate": continue
        for row in m.get("data", []):
            t = datetime.strptime(row["date"][:19], "%Y-%m-%d %H:%M:%S").replace(second=0); v = row.get("Avg") or row.get("Min")
            if v: samples[t] = float(v)          # keyed per MINUTE: app files carry seconds, Shortcut files are minute-stamped

nights = defaultdict(list)
for t, v in samples.items():
    if t.hour >= 23: nights[(t + timedelta(days=1)).date().isoformat()].append((t.timestamp(), v))
    elif t.hour < 10: nights[t.date().isoformat()].append((t.timestamp(), v))

low30 = {}
for wake, s in nights.items():
    s.sort(); best = None
    for i in range(len(s)):
        t0 = s[i][0]; win = [v for t, v in s[i:] if t <= t0 + 1800]
        if len(win) >= 4:
            m = sum(win)/len(win); best = m if best is None else min(best, m)
    if best is not None and len(s) >= 20: low30[wake] = round(best, 1)     # <20 samples = partial night, skip

hist = json.loads(HIST.read_text()) if HIST.exists() else {}
new = {k: v for k, v in low30.items() if hist.get(k) != v}
print("files:", len(list(SRC.rglob('*.json'))), "samples:", len(samples), "nights(>=20 samples):", {k: (len(nights[k]), low30.get(k)) for k in sorted(nights) if len(nights[k]) >= 20})
print("new/changed:", new)
if new and not DRY:
    shutil.copy(HIST, HIST.with_suffix(".json.bak")); hist.update(new)
    HIST.write_text(json.dumps(hist, indent=0, sort_keys=True)); print("low30_history.json updated ->", len(hist), "nights")

# ---- recalibrate est_low30 offset (avgSleepingHR + offset) from every night that has both values ----
if not DRY:
    try:
        import statistics as S, physio_ctx as X
        from datetime import date
        hist = json.loads(HIST.read_text())
        wl = X.api(f"https://intervals.icu/api/v1/athlete/0/wellness?oldest=2026-05-01&newest={date.today()}")
        pairs = [(w["id"], hist[w["id"]], w["avgSleepingHR"]) for w in wl if w.get("avgSleepingHR") and w["id"] in hist]
        d = [l - a for _, l, a in pairs]
        if len(d) >= 2:
            cal = {"median_offset": round(S.median(d), 1), "stdev": round(S.stdev(d), 1), "n_nights": len(d), "period": [pairs[0][0], pairs[-1][0]],
                   "note": "est_low30 = avgSleepingHR + median_offset; recalibrated daily by health_export_low30.py from nights with both values"}
            (ROOT / "wellness/low30_calibration.json").write_text(json.dumps(cal, indent=1)); print("calibration:", cal["median_offset"], "n", cal["n_nights"])
    except Exception as e: print("calibration skipped:", e)

# ---- daily health table: extend features/health_daily.json (rhr, sdnn, sleep_s, + wrist_temp, resp) past the May export ----
# Sources: any Health Auto Export file (daily-aggregated or per-minute). Existing dates from the Apple Health XML are never overwritten.
if not DRY:
    HD = ROOT / "features/health_daily.json"; hd = json.loads(HD.read_text()) if HD.exists() else {}
    day = defaultdict(dict); hrv_by_day = defaultdict(list)
    for f in sorted(SRC.rglob("*.json")):
        try: ms = json.load(open(f)).get("data", {}).get("metrics", [])
        except Exception: continue
        for m in ms:
            for row in m.get("data", []):
                dstr = row.get("date", "")[:10]
                if not dstr: continue
                if m["name"] == "resting_heart_rate" and row.get("qty"): day[dstr]["rhr"] = round(float(row["qty"]), 1)
                elif m["name"] == "sleep_analysis":
                    ts = row.get("totalSleep") or row.get("asleep") or 0
                    if ts: day[dstr]["sleep_s"] = int(float(ts) * 3600)
                elif m["name"] == "heart_rate_variability" and row.get("qty"): hrv_by_day[dstr].append(float(row["qty"]))
                elif m["name"] == "apple_sleeping_wrist_temperature" and row.get("qty"): day[dstr]["wrist_temp"] = round(float(row["qty"]), 2)
                elif m["name"] == "respiratory_rate" and row.get("qty"): day[dstr]["resp"] = round(float(row["qty"]), 1)
                elif "vo2" in m["name"].lower() and row.get("qty"): day[dstr]["vo2max"] = round(float(row["qty"]), 2)   # Apple's walk-based estimate
                elif "alcohol" in m["name"].lower() and row.get("qty") is not None:                 # Apple "Number of Alcoholic Beverages" (1 = ~14 g)
                    day[dstr]["drinks"] = round(day[dstr].get("drinks", 0) + float(row["qty"]), 1)
                elif m["name"] in ("weight_body_mass", "body_mass", "weight") and row.get("qty"): day[dstr]["weight"] = round(float(row["qty"]), 2)
    for dstr, v in hrv_by_day.items(): day[dstr]["sdnn"] = round(sum(v)/len(v), 2)
    added = 0
    for dstr, vals in day.items():
        cur = hd.setdefault(dstr, {})
        for k, v in vals.items():
            if cur.get(k) is None or (k == "drinks" and cur.get(k) != v): cur[k] = v; added += 1
    if added:
        shutil.copy(HD, HD.with_suffix(".json.bak")); HD.write_text(json.dumps(hd, sort_keys=True))
        print(f"health_daily.json: +{added} values, now {min(hd)} .. {max(hd)}")
