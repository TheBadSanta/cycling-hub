#!/usr/bin/env python3
"""Assemble the master research panel: daily + weekly rows, 2017-2026.

Inputs (all on MP100):
  features/workouts.jsonl   — per-workout stream features (power bands, EF, decoupling)
  features/health_daily.json — weight/rhr/sdnn/sleep/vo2max from AH XML (2010-2026)
  wellness/{YYYY}.json       — intervals.icu: ctl/atl, eFTP series, sleep/hrv (recent)
  wellness/low30_history.json — lowest-30' sleeping HR (3,015 nights)

Zone classification is relative to the day's rolling eFTP (intervals sportInfo),
interpolated across gaps. eFTP is systematically low vs Egor's real FTP but
CONSISTENT — fine for trends and zone boundaries.

Zones (% of eFTP): Z1 <55 | Z2 55-75 | TEMPO 76-87 | SST 88-94 | THR 95-105 | VO2 106-125 | AN >125

Output: features/panel_daily.json, features/panel_weekly.json
"""
import json
from pathlib import Path
from datetime import date, timedelta

F = Path("/srv/data/physiology/features")
W = Path("/srv/data/physiology/wellness")

# ---- eFTP daily series from wellness ----
eftp, ctl, atl = {}, {}, {}
for yf in sorted(W.glob("20*.json")):
    for r in json.loads(yf.read_text()):
        d = r["id"]
        ctl[d], atl[d] = r.get("ctl"), r.get("atl")
        for si in (r.get("sportInfo") or []):
            if si.get("type") == "Ride" and si.get("eftp"):
                eftp[d] = si["eftp"]

def interp_series(s):
    """Fill gaps by linear interpolation between known points."""
    if not s:
        return {}
    days = sorted(s)
    out = dict(s)
    d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    known = [(date.fromisoformat(d), s[d]) for d in days]
    ki = 0
    d = d0
    while d <= d1:
        ds = d.isoformat()
        if ds not in out:
            while ki + 1 < len(known) and known[ki + 1][0] < d:
                ki += 1
            (da, va), (db, vb) = known[ki], known[ki + 1]
            frac = (d - da).days / max(1, (db - da).days)
            out[ds] = va + (vb - va) * frac
        else:
            while ki + 1 < len(known) and known[ki + 1][0] <= d:
                ki += 1
        d += timedelta(days=1)
    return out

eftp_i = interp_series(eftp)

ZONES = [("z1", 0, 0.55), ("z2", 0.55, 0.755), ("tempo", 0.755, 0.875), ("sst", 0.875, 0.945),
         ("thr", 0.945, 1.055), ("vo2", 1.055, 1.255), ("an", 1.255, 99)]

# ---- per-day workout aggregates ----
daily = {}
n_rides, n_err = 0, 0
for line in (F / "workouts.jsonl").open():
    try:
        w = json.loads(line)
    except Exception:
        continue
    if "error" in w or not w.get("start"):
        n_err += 1
        continue
    d = w["start"][:10]
    if d < "2017-01-01":
        continue
    ft = eftp_i.get(d)
    day = daily.setdefault(d, {"dur_s": 0, "kj": 0, "tss": 0, "n": 0,
                               **{z[0] + "_s": 0 for z in ZONES},
                               "efs": [], "decs": [], "np_max": 0})
    day["n"] += 1
    day["dur_s"] += w.get("dur_s") or 0
    day["kj"] += w.get("kj") or 0
    # TSS: session value, else compute from NP vs eFTP
    tss = w.get("tss")
    if tss is None and w.get("np") and ft and w.get("dur_s"):
        iff = w["np"] / ft
        tss = iff * iff * w["dur_s"] / 36
    day["tss"] += tss or 0
    if ft and w.get("bands"):
        for band_str, secs in w["bands"].items():
            frac = (int(band_str) + 12.5) / ft
            for zname, lo, hi in ZONES:
                if lo <= frac < hi:
                    day[zname + "_s"] += secs
                    break
    if w.get("np"):
        day["np_max"] = max(day["np_max"], w["np"])
    # comparable EF: steady sub-tempo rides >= 60min with low decoupling
    if w.get("ef") and w.get("np") and ft and 0.55 <= w["np"] / ft <= 0.80 and (w.get("dur_s") or 0) >= 3600:
        if w.get("decoupling_pct") is None or abs(w["decoupling_pct"]) <= 8:
            day["efs"].append(w["ef"])
    if w.get("decoupling_pct") is not None:
        day["decs"].append(w["decoupling_pct"])
    n_rides += 1

health = json.loads((F / "health_daily.json").read_text())
low30 = json.loads((W / "low30_history.json").read_text())

panel = {}
for d, day in daily.items():
    row = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in day.items() if k not in ("efs", "decs")}
    row["ef"] = round(sum(day["efs"]) / len(day["efs"]), 3) if day["efs"] else None
    row["decoupling"] = round(sum(day["decs"]) / len(day["decs"]), 2) if day["decs"] else None
    panel[d] = row
# merge health + wellness onto ALL days (incl. rest days)
d0, d1 = date(2017, 1, 1), max(date.fromisoformat(max(daily)), date.fromisoformat(max(health)))
d = d0
while d <= d1:
    ds = d.isoformat()
    row = panel.setdefault(ds, {})
    h = health.get(ds, {})
    row.update({"weight": h.get("weight"), "rhr": h.get("rhr"), "sdnn": h.get("sdnn"),
                "sleep_s": h.get("sleep_s"), "vo2max_ah": h.get("vo2max"),
                "low30": low30.get(ds), "ctl": ctl.get(ds), "atl": atl.get(ds),
                "eftp": round(eftp_i[ds], 1) if ds in eftp_i else None})
    d += timedelta(days=1)

(F / "panel_daily.json").write_text(json.dumps(panel, indent=0, sort_keys=True))

# ---- weekly aggregate ----
weekly = {}
for ds, row in panel.items():
    d = date.fromisoformat(ds)
    monday = (d - timedelta(days=d.weekday())).isoformat()
    w = weekly.setdefault(monday, {"tss": 0, "dur_s": 0, "kj": 0, "rides": 0,
                                   **{z[0] + "_s": 0 for z in ZONES},
                                   "efs": [], "eftps": [], "weights": [], "rhrs": [], "low30s": [], "sleeps": []})
    for z, _, _ in ZONES:
        w[z + "_s"] += row.get(z + "_s") or 0
    w["tss"] += row.get("tss") or 0
    w["dur_s"] += row.get("dur_s") or 0
    w["kj"] += row.get("kj") or 0
    w["rides"] += row.get("n") or 0
    for src, dst in [("ef", "efs"), ("eftp", "eftps"), ("weight", "weights"),
                     ("rhr", "rhrs"), ("low30", "low30s"), ("sleep_s", "sleeps")]:
        if row.get(src) is not None:
            w[dst].append(row[src])

wk = {}
for m, w in sorted(weekly.items()):
    med = lambda xs: round(sorted(xs)[len(xs) // 2], 3) if xs else None
    wk[m] = {
        "tss": round(w["tss"]), "hours": round(w["dur_s"] / 3600, 1), "kj": w["kj"], "rides": w["rides"],
        **{z[0] + "_min": round(w[z[0] + "_s"] / 60) for z in ZONES},
        "ef": med(w["efs"]), "eftp": med(w["eftps"]), "weight": med(w["weights"]),
        "rhr": med(w["rhrs"]), "low30": med(w["low30s"]), "sleep_h": round(med(w["sleeps"]) / 3600, 2) if w["sleeps"] else None,
    }
(F / "panel_weekly.json").write_text(json.dumps(wk, indent=1))
print(f"panel: {len(panel)} days, {len(wk)} weeks | rides used {n_rides}, parse errors {n_err}")
