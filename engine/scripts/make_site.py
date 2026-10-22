#!/usr/bin/env python3
"""Build the full training site (multi-week, navigable) — 3-row card design.

URL scheme (static, NAS Web Station under the hash root):
  /                    season overview
  /<block-slug>/<n>/   canonical per-week page
  /current/            alias = the week containing today

Card: form hero (CTL/ATL/TSB with bands) + one-line summary + 3-row grid
(plan / actual whole-ride / MS work-only) + full-width compliance footer.
MS = Work-tagged segments, time-window (detected intervals, else plan offsets),
40s onset trim, stitched. Validated vs TP.
"""
import os, json, base64, urllib.request, html, shutil
from collections import deque
from pathlib import Path
from datetime import date, timedelta, datetime, timezone

for line in Path("/srv/_env/.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())

FTP = 275.0
HRMAX = 185.0
ROOT = Path("/srv/data/physiology")
PLANS = ROOT / "plans"
WDIR = ROOT / "wellness"
SITE = ROOT / "outbox/site"
SEASON = json.loads((ROOT / "config/season.json").read_text())
try: RAMP = json.loads((ROOT / "config/ramp.json").read_text())
except Exception: RAMP = None

auth = base64.b64encode(f"API_KEY:{os.environ['INTERVALS_API_KEY']}".encode()).decode()
def api(url):
    r = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "User-Agent": "physiology-engine/0.3"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read())

today = date.today()
this_monday = today - timedelta(days=today.weekday())

# ---- season -> week list ----
weeks = []
for b in SEASON["blocks"]:
    fm = date.fromisoformat(b["first_monday"])
    for i in range(b["weeks"]):
        weeks.append({"block": b["title"], "tag": b["tag"], "slug": b["slug"], "n": i + 1,
                      "nweeks": b["weeks"], "monday": fm + timedelta(days=7*i),
                      "off": b.get("off", False), "focus": b["focus"]})
cur_idx = next((i for i, w in enumerate(weeks) if w["monday"] <= today <= w["monday"] + timedelta(days=6)), None)
if cur_idx is None:
    cur_idx = next((i for i, w in enumerate(weeks) if w["monday"] > today), len(weeks) - 1)

# ---- actuals + wellness ----
lo = weeks[0]["monday"].isoformat()
hi = (this_monday + timedelta(days=8)).isoformat()
acts = api(f"https://intervals.icu/api/v1/athlete/0/activities?oldest={lo}&newest={hi}")
# dedup: same start-minute + type = duplicate sync (e.g. walk from HealthFit + IC).
# Keep the one with more moving_time. Prevents double-counted TSS/duration.
_dedup = {}
for a in acts:
    key = (a.get("start_date_local", "")[:16], a.get("type"))
    if key not in _dedup or (a.get("moving_time") or 0) > (_dedup[key].get("moving_time") or 0):
        _dedup[key] = a
acts = list(_dedup.values())
ACT_BY_ID = {str(a["id"]): a for a in acts}
from physio_ctx import is_indoor as is_indoor_act      # single rule: overrides file, pedals-on-a-Wahoo-file = outdoor (T7 era), virtual devices
# Per day: walks aggregate (rare to have two); rides stay as a LIST so a two-ride
# day (workout + e.g. a kids ride) can assign the best-fit ride to the workout and
# render the rest as their own unplanned cards, instead of merging them into one.
by_day = {}
for a in acts:
    d = a["start_date_local"][:10]
    slot = by_day.setdefault(d, {"walk": [0, 0], "rides": []})
    if a.get("type") == "Walk":
        slot["walk"][0] += a.get("icu_training_load") or 0
        slot["walk"][1] += a.get("moving_time") or 0
        continue
    np_ = a.get("icu_weighted_avg_watts"); ap = a.get("icu_average_watts")
    slot["rides"].append({
        "id": a["id"], "name": a.get("name"), "type": a.get("type"),
        "mt": a.get("moving_time") or 0, "tss": a.get("icu_training_load") or 0,
        "rpe": a.get("icu_rpe"), "feel": a.get("feel"),
        "sum": {
            "tss": a.get("icu_training_load"), "if": (a.get("icu_intensity") or 0)/100 or None,
            "np": np_, "avg_p": ap, "hr": a.get("average_heartrate"),
            "cad": a.get("average_cadence"),
            "vi": round(np_/ap, 2) if np_ and ap else None,
            "kj": round((a.get("icu_joules") or 0)/1000) or (round((ap or 0)*(a.get("moving_time") or 0)/1000) or None),
        },
    })
for _s in by_day.values():
    _s["rides"].sort(key=lambda r: r["mt"], reverse=True)  # longest first = default primary

def assign_rides(day):
    """Split a day's rides into (workout_ride, [other_rides]). For a planned workout,
    the workout = the ride best matching plan duration+TSS; others become unplanned cards.
    No plan -> longest is primary, rest unplanned. Returns (None, []) if no rides."""
    rides = list((by_day.get(day["date"]) or {}).get("rides", []))
    if not rides:
        return None, []
    if day.get("planned_tss"):
        pd, pt = day.get("duration_s") or 0, day.get("planned_tss") or 0
        def score(r):
            s = 0.0
            if pd: s += abs(r["mt"] - pd) / pd
            if pt: s += abs(r["tss"] - pt) / pt
            return s
        wr = min(rides, key=score)
        return wr, [r for r in rides if r["id"] != wr["id"]]
    return rides[0], rides[1:]
wl = api(f"https://intervals.icu/api/v1/athlete/0/wellness?oldest={weeks[0]['monday']}&newest={today}")
W = wl[-1] if wl else {}
ctl, atl = W.get("ctl"), W.get("atl")
tsb = round(ctl - atl, 1) if ctl is not None and atl is not None else None

wl_ct = {r["id"]: (r["ctl"], r["atl"]) for r in wl if r.get("ctl") is not None and r.get("atl") is not None}
plan_tss = {}
for pf in PLANS.glob("week-*.json"):
    for dd in json.loads(pf.read_text())["days"]:
        plan_tss[dd["date"]] = plan_tss.get(dd["date"], 0) + (dd.get("planned_tss") or 0)
proj = {}
if wl_ct:
    seed = max(wl_ct); pc, pa = wl_ct[seed]; d = date.fromisoformat(seed)
    end = weeks[-1]["monday"] + timedelta(days=6)
    while d < end:
        d += timedelta(days=1); ds = d.isoformat()
        t = plan_tss.get(ds, 0); pc += (t-pc)/42; pa += (t-pa)/7; proj[ds] = (pc, pa)

# continuous daily CTL/ATL series (measured past/today + projected future), used so
# TSB can look back one day. IC/TP convention: Form(D) = CTL(D-1) - ATL(D-1) — the
# balance carried INTO the day, BEFORE that day's load. wl_ct/proj hold END-of-day
# values (today's already includes today's ride), so same-day CTL-ATL is a day early.
ctl_atl = dict(wl_ct); ctl_atl.update(proj)
def form_for(dstr):
    if dstr in wl_ct: c, a = wl_ct[dstr]; src = "actual"
    elif dstr in proj: c, a = proj[dstr]; src = "plan"
    else: return None
    prev = ctl_atl.get((date.fromisoformat(dstr) - timedelta(days=1)).isoformat())
    pc, pa = prev if prev else (c, a)   # first day of the series has no prior -> same-day
    return round(c), round(a), round(pc - pa), src

try:
    low30_hist = json.loads((WDIR / "low30_history.json").read_text())
    low30_off = json.loads((WDIR / "low30_calibration.json").read_text())["median_offset"]
except Exception:
    low30_hist, low30_off = {}, -1.0

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
def fmt_dur(s): return "—" if not s else f"{int(s//3600)}:{int(s%3600//60):02d}"
def seg_lohi(s): return (s[2], s[2]) if s[0] == "ss" else (s[2], s[3])
def seg_mean(s): return s[2] if s[0] == "ss" else (s[2]+s[3])/2
def seg_role(s): return s[-1] if isinstance(s[-1], str) else "filler"
def kj_plan(segs): return round(sum(s[1]*seg_mean(s)/100*FTP for s in segs)/1000) if segs else None
def np_plan(segs):
    if not segs: return None
    tot = sum(s[1] for s in segs)
    return round((sum((seg_mean(s)/100*FTP)**4 * s[1] for s in segs)/tot)**0.25) if tot else None

# ---- coloring ----
def zcolor(pct):
    if pct < 55: return "#8a8a8e"
    if pct < 75.5: return "#3f8fd8"
    if pct < 87.5: return "#4f9e57"
    if pct < 94.5: return "#2e8b3d"
    if pct < 105.5: return "#c79a1e"
    if pct < 125.5: return "#e08a3c"
    return "#c0392b"

def hr_class(hr):
    if not hr: return ""
    p = hr / HRMAX * 100
    return ("hz1" if p < 60 else "hz2" if p < 75 else "hz3" if p < 82 else
            "hz4" if p < 88 else "hz5" if p < 93 else "hz6" if p < 97 else "hz7")

def drift_class(d):
    a = abs(d); return "dg" if a < 3 else "dy" if a < 5 else "do"

def tsb_class(v):
    return ("tsb-blue" if v > 5 else "tsb-grey" if v >= -5 else
            "tsb-green" if v >= -15 else "tsb-orange" if v >= -25 else "tsb-red")

def profile_svg(segs):
    if not segs: return ""
    W_, H, PAD = 236, 114, 8
    total = sum(s[1] for s in segs)
    maxp = max(120, max(seg_lohi(s)[1] for s in segs) + 5)
    def y(p): return H - PAD - p/maxp*(H-2*PAD)
    x, sh = PAD, []
    for s in segs:
        bw = s[1]/total*(W_-2*PAD); lo, hi = seg_lohi(s)
        if s[0] == "ss":
            sh.append(f'<rect x="{x:.1f}" y="{y(lo):.1f}" width="{max(bw,1):.1f}" height="{H-PAD-y(lo):.1f}" fill="{zcolor(lo)}"/>')
        else:
            sh.append(f'<polygon points="{x:.1f},{H-PAD} {x:.1f},{y(lo):.1f} {x+bw:.1f},{y(hi):.1f} {x+bw:.1f},{H-PAD}" fill="{zcolor((lo+hi)/2)}"/>')
        x += bw
    return (f'<svg viewBox="0 0 {W_} {H}" preserveAspectRatio="none">'
            f'<line x1="0" y1="{y(100):.1f}" x2="{W_}" y2="{y(100):.1f}" stroke="#4a505b" stroke-dasharray="3,4" stroke-width="1"/>'
            + "".join(sh) + "</svg>")

# ---- MS + whole-ride metrics from streams (cached per activity) ----
CACHE_PATH = ROOT / "features/card_cache.json"
try: CACHE = json.loads(CACHE_PATH.read_text())
except Exception: CACHE = {}
# drop entries predating a schema field so they recompute once (e.g. indoor/outdoor)
CACHE = {k: v for k, v in CACHE.items() if isinstance(v, dict) and "outdoor" in v}

def np_roll(p):
    q = deque(); s = 0.0; out = []
    for x in p:
        x = x or 0; q.append(x); s += x
        if len(q) > 30: s -= q.popleft()
        if len(q) == 30: out.append((s/30)**4)
    return (sum(out)/len(out))**0.25 if out else (sum(p)/len(p) if p else 0)

def _decouple(idxs, watts, hrs):
    """TP aerobic decoupling: avg-power:HR per half, (r1-r2)/r1*100 (first-half base)."""
    idxs = [i for i in idxs if watts[i] is not None and hrs[i] and hrs[i] > 60]
    if len(idxs) < 120: return None
    h = len(idxs)//2
    def ratio(chunk):
        pw = sum(watts[i] for i in chunk)/len(chunk); hh = sum(hrs[i] for i in chunk)/len(chunk)
        return pw/hh if hh else None
    r1, r2 = ratio(idxs[:h]), ratio(idxs[h:])
    return round((r1-r2)/r1*100, 1) if r1 and r2 else None

def compute_activity(aid, work_segs, segs):
    """work_segs: list of (target_watts, planned_sec). Returns {whole_drift, ms:{...}} or partial."""
    key = str(aid); act = ACT_BY_ID.get(key)
    if key in CACHE:
        if act: CACHE[key]["outdoor"] = not is_indoor_act(act)   # re-read every refresh so a retype/rename is never stale
        return CACHE[key]
    out = {"whole_drift": None, "hr_drop60": None, "ms": None, "outdoor": (not is_indoor_act(act)) if act else None}
    try:
        st = api(f"https://intervals.icu/api/v1/activity/{aid}/streams?types=watts,heartrate,cadence,latlng")
        watts = next((s["data"] for s in st if s["type"] == "watts"), None)
        hrs = next((s["data"] for s in st if s["type"] == "heartrate"), None)
        cads = next((s["data"] for s in st if s["type"] == "cadence"), None)
        # GPS track present -> outdoor; none -> indoor (FTMS trainer). Egor's rule.
        if out["outdoor"] is None:
            ll = next((s["data"] for s in st if s["type"] == "latlng"), None)
            out["outdoor"] = bool(ll and any(p for p in ll))
    except Exception:
        watts = hrs = cads = None
    if not watts:
        CACHE[key] = out; return out
    n = len(watts)
    if hrs is None: hrs = [None]*n
    if cads is None: cads = [None]*n
    out["whole_drift"] = _decouple(range(n), watts, hrs)

    # 1-min HR drop: max HR decline across ANY 60s window (usually ~7s into a
    # recovery valley after work). Durability / parasympathetic reactivation — Egor's key metric.
    best = 0
    for i in range(n - 60):
        a, b = hrs[i], hrs[i + 60]
        if a and b and a > 30 and b > 30 and (a - b) > best:
            best = a - b
    out["hr_drop60"] = round(best) if best > 0 else (0 if any(hrs) else None)

    if work_segs:
        targets = [tw for tw, _ in work_segs]
        # === Workout matching (2026-07-21): TIMING-FIRST via device laps ===
        # Egor: "timing tells everything." When a workout runs on the head unit, each
        # step writes a lap — the plan's duration sequence is a unique fingerprint.
        # 1) LAP MATCH (primary): greedy in-order alignment of plan segments to laps.
        #    1:1 when durations agree (tol max(15s,10%)); a big lap swallows consecutive
        #    segments (coarse lapping) -> segments placed by PLAN OFFSETS inside the blob;
        #    extra laps before/after = pre-workout / extended riding. Valid only with
        #    >=3 one-to-one anchors (a single-lap free ride is NOT timing evidence).
        #    Work windows come straight from their lap boundaries — exact.
        # 2) PROFILE FALLBACK (lap-less rides): slide expected power over actual
        #    (30s ds, err = mean|a-e|/FTP, attempted iff err <= 0.115 — calibrated).
        # 3) ±10% power check per work window = "rep executed" (metric hygiene only:
        #    failed window counts against in-target score, excluded from EF/drift).
        lap_windows, anchors = None, 0
        try:
            laps = (api(f"https://intervals.icu/api/v1/activity/{aid}/intervals") or {}).get("icu_intervals") or []
            laps = [(iv.get("start_index"), iv.get("end_index")) for iv in laps
                    if iv.get("start_index") is not None and iv.get("end_index") is not None]
        except Exception:
            laps = []
        ss_segs = [(s[1], seg_role(s) == "work") for s in segs]  # (dur, is_work) in order
        if len(laps) >= 3:
            # 2026-10-14: greedy walk replaced by an exact alignment (DP over plan-segment x lap).
            # A lap may now be SKIPPED at no gain: a 1-3 s glitch lap from a pause/resume, an aborted
            # first attempt, or pre-workout riding no longer eats a plan segment and shifts every later
            # rep onto the wrong lap (Oct 10 SST 7x9' scored "MS 6%, 6 reps missed" that way).
            def tol(d): return max(15, d * 0.10)
            MINLAP = 20                        # laps shorter than this are never a user-advanced step
            NS, NL = len(ss_segs), len(laps)
            from functools import lru_cache
            @lru_cache(maxsize=None)
            def solve(i, j):
                """best (anch, matched_dur, -skips, wins, reached) from plan segment i / lap j onward."""
                if i >= NS or j >= NL: return (0, 0, 0, (), i)
                sd, isw = ss_segs[i]; l0, l1 = laps[j]; ld = l1 - l0
                cands = []
                a, d, k, w, r = solve(i, j + 1); cands.append((a, d, k - 1, w, r))    # skip this lap
                if abs(ld - sd) <= tol(sd):                                        # 1:1 anchor
                    a, d, k, w, r = solve(i + 1, j + 1)
                    cands.append((a + 1, d + sd, k, ((l0, l1),) + w if isw else w, max(r, i + 1)))
                elif ld > sd:                                                      # blob: segments placed by plan offsets
                    ii, consumed, wins, dur = i, 0, (), 0
                    while ii < NS and consumed + ss_segs[ii][0] <= ld + tol(ss_segs[ii][0]):
                        sd2, isw2 = ss_segs[ii]
                        if isw2: wins += ((l0 + consumed, min(l0 + consumed + sd2, l1)),)
                        consumed += sd2; dur += sd2; ii += 1
                    if ii > i:
                        a, d, k, w, r = solve(ii, j + 1); cands.append((a, d + dur, k, wins + w, max(r, ii)))
                elif ld >= MINLAP:                                                 # shorter: user-advanced step (not an anchor)
                    a, d, k, w, r = solve(i + 1, j + 1)
                    cands.append((a, d + ld, k, ((l0, l1),) + w if isw else w, max(r, i + 1)))
                return max(cands, key=lambda c: (c[0], c[1], c[2]))
            best = None
            for j0 in range(min(NL, 6)):                                           # pre-workout laps may be skipped
                a, d, k, w, r = solve(0, j0)
                if a >= 3 and r >= 0.7 * NS and (best is None or (a, d, k) > best[0]):   # same validity as before: >=3 anchors, 70% of segments reached
                    best = ((a, d, k), list(w), a)
            solve.cache_clear()
            if best:
                lap_windows, anchors = best[1], best[2]
        out["lap_match"] = anchors
        if lap_windows is not None:
            attempted = True
            cand_windows = [(max(0, a0), min(a1, n)) for a0, a1 in lap_windows]
            out["align"] = {"err": None, "t0": (cand_windows[0][0] if cand_windows else 0), "via": "laps"}
        else:
            # profile fallback for lap-less rides
            exp = []
            for s in segs:
                if s[0] == "ss":
                    exp += [s[2] / 100 * FTP] * s[1]
                else:
                    exp += [(s[2] + (s[3] - s[2]) * i / s[1]) / 100 * FTP for i in range(s[1])]
            DS = 30
            A = [sum(x or 0 for x in watts[i:i+DS]) / max(1, len(watts[i:i+DS])) for i in range(0, n, DS)]
            E = [sum(exp[i:i+DS]) / max(1, len(exp[i:i+DS])) for i in range(0, len(exp), DS)]
            best_err, best_score, t0 = None, None, 0
            max_t0 = max(0, len(A) - int(len(E) * 0.6))
            for c in range(0, max_t0 + 1):
                seg = A[c:c + len(E)]
                m = min(len(seg), len(E))
                if m < len(E) * 0.6: break
                err = sum(abs(seg[i] - E[i]) for i in range(m)) / m / FTP
                # penalize partial overlap + prefer smallest t0 on near-ties
                score = err + 0.08 * (1 - m / len(E)) + 0.0004 * c
                if best_score is None or score < best_score:
                    best_score, best_err, t0 = score, err, c * DS
            out["align"] = {"err": round(best_err, 3) if best_err is not None else None, "t0": t0, "via": "profile"}
            attempted = best_err is not None and best_err <= 0.115
            cand_windows = []
            if attempted:
                off = 0
                for s in segs:
                    if s[0] == "ss" and seg_role(s) == "work":
                        ws, dur_s = t0 + off, s[1]
                        tw = s[2] / 100 * FTP
                        # snap +-240s to best mean-power fit
                        best_d, best_shift = None, 0
                        for shift in range(-240, 241, 10):
                            a0 = ws + shift
                            if a0 < 0 or a0 + dur_s > n: continue
                            vals = [watts[i] or 0 for i in range(a0, a0 + dur_s)]
                            dmean = abs(sum(vals) / dur_s - tw)
                            if best_d is None or dmean < best_d: best_d, best_shift = dmean, shift
                        a0 = max(0, min(ws + best_shift, n - 1)); a1 = min(a0 + dur_s, n)
                        cand_windows.append((a0, a1))
                    off += s[1]
        out["attempted"] = attempted

        # ±10% executed-check per work window (metric hygiene — Egor's 2nd criterion)
        windows, missed_windows = [], []
        wt = [s[2] / 100 * FTP for s in segs if s[0] == "ss" and seg_role(s) == "work"]
        for k, (a0, a1) in enumerate(cand_windows if attempted else []):
            vals = [watts[i] or 0 for i in range(a0, a1)]
            if not vals: continue
            tw = wt[k] if k < len(wt) else wt[-1]
            if abs(sum(vals) / len(vals) - tw) / tw <= 0.10:
                windows.append((a0, a1))
            else:
                missed_windows.append((a0, a1))
        out["ms_missed"] = len(missed_windows)
        if windows:
            planned_total = sum(sec for _, sec in work_segs)
            in_target = 0; work_total = 0
            trimmed = []
            for (s0, s1) in windows:
                work_total += (s1 - s0)
                q = deque(); ssum = 0.0
                for i in range(s0, s1):
                    x = watts[i] or 0; q.append(x); ssum += x
                    if len(q) > 30: ssum -= q.popleft()
                    avg = ssum/len(q)
                    if any(abs(avg-tw)/tw <= 0.05 for tw in targets):
                        in_target += 1
                trimmed += list(range(min(s0+40, s1), s1))
            tset = [i for i in trimmed if watts[i] is not None]
            if tset:
                avgp = sum(watts[i] for i in tset)/len(tset)
                # NP: per-window (trimmed) rolling, dur-weighted
                npv, dur_w = 0.0, 0
                for (s0, s1) in windows:
                    seg = [watts[i] or 0 for i in range(min(s0+40, s1), s1)]
                    if seg: npv += np_roll(seg)*len(seg); dur_w += len(seg)
                npw = npv/dur_w if dur_w else avgp
                hv = [hrs[i] for i in tset if hrs[i] and hrs[i] > 60]
                cv = [cads[i] for i in tset if cads[i] is not None]
                hr = sum(hv)/len(hv) if hv else None
                dur = work_total
                iff = npw/FTP
                ms = {
                    "dur": dur, "np": round(npw), "avg_p": round(avgp),
                    "hr": round(hr) if hr else None,
                    "cad": round(sum(cv)/len(cv)) if cv else None,
                    "if": round(iff, 2), "tss": round(iff*iff*dur/36),
                    "kj": round(avgp*dur/1000),
                    "vi": round(npw/avgp, 2) if avgp else None,
                    "ef": round(npw/hr, 2) if hr else None,
                    "drift": _decouple(trimmed, watts, hrs),
                    "score": min(100, round(in_target/planned_total*100)) if planned_total else None,
                }
                out["ms"] = ms
    CACHE[key] = out
    return out

def wc_cls(delta):
    return "green" if -5 <= delta <= 10 else "yellow" if delta > 10 else "orange" if -10 <= delta < -5 else "red"

def status_for(day):
    d = date.fromisoformat(day["date"]); planned = day["planned_tss"]
    slot = by_day.get(day["date"], {"walk": [0, 0], "rides": []})
    if day["type"] == "Walk":
        actual, adur = slot.get("walk", [0, 0])
    else:
        wr, _ = assign_rides(day)          # compliance is against the WORKOUT ride only
        actual, adur = (wr["tss"], wr["mt"]) if wr else (0, 0)
    if planned == 0:
        return ("rest", "rest", actual, adur) if actual == 0 else ("green", f"+{round(actual)} bonus", actual, adur)
    if actual > 0:
        tss_d = (actual-planned)/planned*100
        dur_d = (adur-day["duration_s"])/day["duration_s"]*100 if day.get("duration_s") else tss_d
        sev = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
        return (max((wc_cls(tss_d), wc_cls(dur_d)), key=lambda c: sev[c]), (tss_d, dur_d), actual, adur)
    if d > today: return ("up", "upcoming", 0, 0)
    if d == today: return ("today", "today", 0, 0)
    return ("red", "missed", 0, 0)

HEAD = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>{title}</title>
<style>
:root{{--bg:#eaeef3;--card:#fff;--inset:#f1f4f8;--ink:#12151b;--muted:#5f6b7a;--faint:#9aa3af;--line:#e2e7ee;--line2:#eef1f5;--accent:#2563eb;--panel:#0c0d11;--panel-line:#33383f;--good:#1f9d4d;--warn:#c9930f;--mid:#dd7b1e;--bad:#d23b3b;--z1:#8a8a8e;--z2:#3f8fd8;--tempo:#4f9e57;--sst:#2e8b3d;--thr:#c79a1e;--vo2:#e08a3c;--an:#c0392b}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0e1013;--card:#181b20;--inset:#111417;--ink:#e9edf2;--muted:#98a2b0;--faint:#66707d;--line:#282d34;--line2:#20242a;--accent:#6ea8fe;--panel:#0a0b0e;--panel-line:#333842;--good:#33c268;--warn:#e3b52c;--mid:#ef913a;--bad:#ef5350;--z2:#4f97dc;--tempo:#5fae67;--sst:#3aa34c;--thr:#e0b839}}}}
:root[data-theme="dark"]{{--bg:#0e1013;--card:#181b20;--inset:#111417;--ink:#e9edf2;--muted:#98a2b0;--faint:#66707d;--line:#282d34;--line2:#20242a;--accent:#6ea8fe;--panel:#0a0b0e;--panel-line:#333842;--good:#33c268;--warn:#e3b52c;--mid:#ef913a;--bad:#ef5350;--z2:#4f97dc;--tempo:#5fae67;--sst:#3aa34c;--thr:#e0b839}}
:root[data-theme="light"]{{--bg:#eaeef3;--card:#fff;--inset:#f1f4f8;--ink:#12151b;--muted:#5f6b7a;--faint:#9aa3af;--line:#e2e7ee;--line2:#eef1f5;--accent:#2563eb;--panel:#0c0d11;--panel-line:#33383f;--good:#1f9d4d;--warn:#c9930f;--mid:#dd7b1e;--bad:#d23b3b;--z2:#3f8fd8;--tempo:#4f9e57;--sst:#2e8b3d;--thr:#c79a1e}}
*{{box-sizing:border-box}}html{{-webkit-text-size-adjust:100%}}
body{{margin:0 auto;max-width:1080px;padding:22px 18px 70px;font:15px/1.5 -apple-system,"SF Pro Text",system-ui,sans-serif;font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1;color:var(--ink);background:var(--bg)}}
a{{color:var(--accent);text-decoration:none}}
h1{{font-size:22px;font-weight:700;margin:0 0 2px;letter-spacing:-.01em}}
.sub{{color:var(--muted);margin:0 0 14px;font-size:14px}}
.nav{{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:0 0 16px;font-size:14px}}
.nav a,.nav span{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:7px 12px}}
.nav .mid{{flex:1;text-align:center;color:var(--muted)}}
.statbar,.wellbar{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}}
.statbar div,.wellbar div{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:9px 14px;flex:1 1 96px;text-align:center}}
.statbar b,.wellbar b{{display:block;font-size:19px;font-weight:700}}.statbar span,.wellbar span{{color:var(--muted);font-size:11.5px}}
.wellbar div{{flex:1 1 70px;padding:7px 9px}}.wellbar b{{font-size:16px}}
h2{{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:22px 0 9px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:18px;box-shadow:0 1px 2px rgba(10,15,30,.04),0 10px 26px -20px rgba(10,15,30,.28);overflow:hidden;margin:12px 0}}
.card.today{{outline:2px solid var(--accent);outline-offset:-1px}}
.card.done-green{{outline:2px solid var(--good);outline-offset:-1px}}
.card.done-yellow{{outline:2px solid var(--warn);outline-offset:-1px}}
.card.done-orange{{outline:2px solid var(--mid);outline-offset:-1px}}
.card.done-red{{outline:2px solid var(--bad);outline-offset:-1px}}
.chead{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px;padding:14px 18px;border-bottom:1px solid var(--line2)}}
.ident{{min-width:0}}
.dow{{font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}}
.iotag{{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:99px;font-size:10px;font-weight:800;letter-spacing:.04em;vertical-align:1px;border:1px solid var(--line)}}
.iotag.out{{color:var(--tempo);border-color:var(--tempo)}}
.iotag.ind{{color:var(--z2);border-color:var(--z2)}}
.card.extra{{margin-top:-4px}}
.wname{{font-size:18px;font-weight:700;letter-spacing:-.015em;line-height:1.2;margin-top:1px}}
.wsum{{font-size:13px;color:var(--muted);margin-top:3px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.form{{grid-column:2;justify-self:center;display:flex;align-items:stretch;background:var(--inset);border:1px solid var(--line);border-radius:13px;padding:5px 4px}}
.form .ftag{{font-size:9px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);align-self:center;padding:0 11px 0 8px;line-height:1.25;text-align:right}}
.form .fx{{padding:2px 14px;text-align:center;border-left:1px solid var(--line)}}
.form .fv{{font-size:22px;font-weight:750;line-height:1;letter-spacing:-.02em}}
.form .fl{{font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);margin-top:5px}}
.form.plan .fv{{color:var(--muted)}}
.tsb-blue{{color:var(--accent)}}.tsb-grey{{color:var(--muted)}}.tsb-green{{color:var(--good)}}.tsb-orange{{color:var(--mid)}}.tsb-red{{color:var(--bad)}}
.cbody{{display:flex;gap:18px;padding:18px;align-items:stretch}}
@media(max-width:640px){{.cbody{{flex-wrap:wrap}}}}
.viz{{flex:0 0 236px;min-height:96px;background:var(--panel);border-radius:13px;border:1px solid var(--panel-line);padding:11px 12px;display:flex}}
.viz svg{{display:block;width:100%;height:100%}}
.viz.ghost{{background:var(--inset);border:1px solid var(--line);align-items:center;justify-content:center;flex-direction:column;gap:8px}}
.viz.ghost .gi{{font-size:24px;opacity:.55}}.viz.ghost .gt{{font-size:11.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--faint)}}
.data{{flex:1 1 340px;min-width:280px;display:flex;flex-direction:column;gap:11px}}
.panel{{background:var(--inset);border:1px solid var(--line);border-radius:12px;padding:12px 15px}}
.data .panel{{flex:1;display:flex;flex-direction:column;justify-content:center}}
.grid{{display:grid;grid-template-columns:52px repeat(11,1fr);align-items:end;row-gap:2px;width:100%}}
.grid .h{{font-size:9.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--faint);text-align:right;padding:0 0 3px}}
.grid .rl{{font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);align-self:center;white-space:nowrap}}
.grid .rl.act{{color:var(--good)}}.grid .rl.ms{{color:var(--accent)}}
.grid .v{{font-size:15px;font-weight:650;text-align:right;line-height:1.4;color:var(--ink)}}
.grid .v.dash{{color:var(--faint);font-weight:500}}
.grid .v.green{{color:var(--good)}}.grid .v.blue{{color:var(--accent)}}
.grid .v.hz1{{color:var(--z1)}}.grid .v.hz2{{color:var(--z2)}}.grid .v.hz3{{color:var(--tempo)}}.grid .v.hz4{{color:var(--sst)}}.grid .v.hz5{{color:var(--thr)}}.grid .v.hz6{{color:var(--vo2)}}.grid .v.hz7{{color:var(--an)}}
.grid .v.dg{{color:var(--good)}}.grid .v.dy{{color:var(--warn)}}.grid .v.do{{color:var(--mid)}}
.grid .sep{{grid-column:1/-1;height:1px;background:var(--line);margin:4px 0}}
.compbar{{display:flex;flex-wrap:wrap;gap:7px;align-items:center;padding:12px 18px;border-top:1px solid var(--line2);background:var(--inset)}}
.compbar .cl{{font-size:9.5px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-right:4px}}
.pill{{display:inline-flex;align-items:baseline;gap:6px;padding:5px 12px;border-radius:99px;font-size:13px;font-weight:700;background:var(--card);border:1px solid var(--line)}}
.pill .pk{{font-size:9px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;color:var(--faint)}}
.pill.good{{color:var(--good);border-color:color-mix(in srgb,var(--good) 34%,transparent)}}
.pill.yellow{{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 34%,transparent)}}
.pill.orange{{color:var(--mid);border-color:color-mix(in srgb,var(--mid) 34%,transparent)}}
.pill.red{{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 34%,transparent)}}
.pill.na{{color:var(--faint)}}
.blk{{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:14px 16px;margin:12px 0}}
.blkhead{{display:flex;justify-content:space-between;align-items:baseline}}
.blktitle{{font-size:17px;font-weight:700}}.blktag{{color:var(--muted);font-size:12px}}
.blkfocus{{color:var(--muted);font-size:13.5px;margin:4px 0 10px}}
.wkrow{{display:flex;flex-wrap:wrap;gap:7px}}
.wk{{display:block;background:var(--inset);border:1px solid var(--line);border-radius:10px;padding:7px 11px;font-size:13.5px;min-width:64px;text-align:center}}
.wk.cur{{border-color:var(--accent);border-width:2px;font-weight:700}}.wk.off{{opacity:.55}}.wk small{{display:block;color:var(--muted);font-size:11px}}
.rest{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:16px 18px}}
.rest .rn{{font-size:16px;font-weight:700;color:var(--muted)}}
.desc{{padding:12px 18px;font-size:13px;color:var(--muted);line-height:1.5;border-top:1px solid var(--line2)}}
.foot{{color:var(--faint);font-size:11.5px;margin-top:24px}}
@media(max-width:560px){{
  body{{padding:14px 10px 56px}}
  .chead{{grid-template-columns:1fr;gap:10px}}
  .form{{grid-column:1;justify-self:start}}
  .cbody{{flex-direction:column;gap:12px;padding:14px;align-items:stretch}}
  .viz{{flex:0 0 auto;width:100%;height:104px}}
  .data{{min-width:0;width:100%;flex:0 0 auto}}
  /* panel becomes a plain horizontal scroll container (override desktop flex-centering) */
  /* no side padding on the scroller: sticky label pins flush to the card edge, no gap for cells to peek through */
  .data .panel{{flex:0 0 auto;display:block;overflow-x:auto;padding:12px 0}}
  .grid{{min-width:648px;grid-template-columns:64px repeat(11,minmax(46px,1fr))}}
  .grid .v,.grid .h{{padding-left:4px}}
  /* pin the Plan/Actual/MS label column while the metrics scroll (iOS: no -webkit-overflow-scrolling, it kills sticky) */
  .grid .rl,.grid .h:first-child{{position:-webkit-sticky;position:sticky;left:0;z-index:2;align-self:stretch;display:flex;align-items:center;padding-left:12px;background:var(--inset);box-shadow:1px 0 0 var(--line)}}
  .statbar div,.wellbar div{{flex:1 1 44%}}
  .tabbar{{margin:0 -18px 16px}}
  .atpgrid{{grid-template-columns:1fr}}
}}
/* --- Firefox-style tab bar --- */
.tabbar{{display:flex;gap:4px;align-items:flex-end;border-bottom:1px solid var(--line);margin:0 0 18px;padding:0 2px}}
.tabbar a{{padding:9px 18px;border-radius:10px 10px 0 0;font-size:14px;font-weight:600;color:var(--muted);
  border:1px solid transparent;border-bottom:none;position:relative;top:1px;display:flex;align-items:center;gap:7px}}
.tabbar a .ico{{font-size:15px}}
.tabbar a:hover{{color:var(--ink);background:var(--inset)}}
.tabbar a.on{{color:var(--ink);background:var(--card);border-color:var(--line);border-bottom:1px solid var(--card)}}
.tabbar a.off{{color:var(--faint);pointer-events:none}}
.tabbar a.off small{{font-size:10px;opacity:.7}}
/* --- ATP chart + table --- */
.atpwrap{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 16px 8px;margin:0 0 16px}}
.atpwrap svg{{display:block;width:100%;height:auto}}
.leg{{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin:6px 2px 0}}
.leg i{{display:inline-block;width:18px;height:0;border-top:3px solid currentColor;vertical-align:middle;margin-right:6px}}
.leg .dash{{border-top-style:dashed}}
.atptbl{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table.atp{{border-collapse:collapse;width:100%;min-width:640px;font-size:13.5px}}
table.atp th{{text-align:right;color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;padding:8px 10px;border-bottom:1px solid var(--line)}}
table.atp th:first-child,table.atp td:first-child{{text-align:left}}
table.atp td{{text-align:right;padding:9px 10px;border-bottom:1px solid var(--line2)}}
table.atp tr.now td{{background:var(--inset)}}
table.atp tr.down td{{color:var(--muted)}}
table.atp a{{font-weight:600}}
.blkchip{{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11px;font-weight:700;border:1px solid var(--line)}}
/* --- Today tab --- */
.todhead{{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin:0 0 4px}}
.findings{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:6px 18px;margin:14px 0}}
.finding{{display:flex;gap:11px;padding:12px 0;border-bottom:1px solid var(--line2);align-items:flex-start}}
.finding:last-child{{border-bottom:none}}
.finding .fi{{font-size:17px;line-height:1.3;flex:0 0 auto}}
.finding .ft{{font-size:14px;line-height:1.45}}
.finding .ft b{{font-weight:700}}
.finding.good .fi{{color:var(--good)}}.finding.warn .fi{{color:var(--mid)}}.finding.bad .fi{{color:var(--bad)}}
</style></head><body>"""

def T(v, cls=""):
    return f'<div class="v{(" "+cls) if cls else ""}">{v}</div>'
COLS = ["dur", "TSS", "IF", "NP", "kJ", "CAD", "HR", "EF", "VI", "Pw:HR", "1'↓HR"]

def form_hero(dstr):
    f = form_for(dstr)
    if not f: return ""
    fc, fa, ftsb, src = f
    pc = " plan" if src == "plan" else ""
    return (f'<div class="form{pc}"><span class="ftag">Form<br>{src}</span>'
            f'<div class="fx"><div class="fv">{fc}</div><div class="fl">CTL</div></div>'
            f'<div class="fx"><div class="fv">{fa}</div><div class="fl">ATL</div></div>'
            f'<div class="fx"><div class="fv {tsb_class(ftsb)}">{ftsb:+d}</div><div class="fl">TSB</div></div></div>')

def grid_row(label, cells, rl_cls=""):
    return f'<div class="rl {rl_cls}">{label}</div>' + "".join(cells)

GENERIC = {"cycling", "ride", "workout", "indoor cycling", "virtual ride", "evening ride",
           "morning ride", "afternoon ride", "night ride", "lunch ride", "any ride",
           "evening virtual ride", "night virtual ride", "outdoor cycling", "gravel ride"}
def named(rname):
    """IC ride name if it's a real custom name, else None (skip generic auto-names)."""
    return rname if rname and rname.strip().lower() not in GENERIC else None

def iotag(ca):
    """indoor/outdoor pill from GPS presence; nothing if unknown."""
    if not ca or ca.get("outdoor") is None: return ""
    return ('<span class="iotag out">Outdoor</span>' if ca["outdoor"]
            else '<span class="iotag ind">Indoor</span>')

FEEL_TXT = {1: "strong", 2: "good", 3: "normal", 4: "tired", 5: "weak"}
def subj_pills(ride):
    """Egor's own marks from intervals.icu: RPE 1-10 and feel 1-5 (1 = strong, 5 = weak). Nothing if not rated yet."""
    if not ride: return []
    out = []
    rpe, feel, if_ = ride.get("rpe"), ride.get("feel"), (ride.get("sum") or {}).get("if") or 0
    if rpe is not None:
        # hard-felt easy ride = earliest fatigue signal (doctrine); otherwise neutral
        rc = "orange" if (rpe >= 7 and if_ <= 0.70) else "red" if rpe >= 9 else "na"
        out.append(f'<span class="pill {rc}"><span class="pk">RPE</span>{rpe}/10</span>')
    if feel is not None:
        fc = {1: "good", 2: "good", 3: "na", 4: "orange", 5: "red"}.get(feel, "na")
        out.append(f'<span class="pill {fc}"><span class="pk">Feel</span>{FEEL_TXT.get(feel, feel)}</span>')
    return out

def actual_cells(adur, actual_tss, rs, ca, dc=""):
    wd = ca["whole_drift"] if ca else None
    return [T(fmt_dur(adur), dc.strip()), T(round(actual_tss), dc.strip()),
            T(f'{rs["if"]:.2f}' if rs.get("if") else "–", dc.strip() or ("dash" if not rs.get("if") else "")),
            T(round(rs["np"]) if rs.get("np") else "–", dc.strip()),
            T(rs.get("kj") or "–", dc.strip()),
            T(round(rs["cad"]) if rs.get("cad") else "–"),
            T(round(rs["hr"]) if rs.get("hr") else "–", hr_class(rs.get("hr"))),
            T(round(rs["np"]/rs["hr"], 2) if rs.get("np") and rs.get("hr") else "–"),
            T(rs.get("vi") or "–"),
            T(f'{wd:+.1f}%' if wd is not None else "–", drift_class(wd) if wd is not None else "dash"),
            T(f'{ca["hr_drop60"]}' if ca and ca.get("hr_drop60") else "–")]

def extra_ride_card(day, ride):
    """A second+ ride on a day (e.g. kids ride alongside the workout) -> its own
    neutral unplanned card. Uses the IC custom name and indoor/outdoor tag."""
    d = date.fromisoformat(day["date"])
    ca = compute_activity(ride["id"], [], []) if d <= today else None
    rs = ride["sum"]
    name = named(ride["name"]) or "Unplanned ride"
    sub = "Unplanned ride" if named(ride["name"]) else ""
    header = "".join(f'<div class="h">{c}</div>' for c in COLS)
    row = grid_row("Actual", actual_cells(ride["mt"], ride["tss"], rs, ca, ""), "act")
    grid = f'<div class="panel"><div class="grid"><div class="h"></div>{header}{row}</div></div>'
    viz = ('<div class="viz ghost"><div class="gi">🚲</div><div class="gt">Unplanned ride</div></div>')
    sumline = f'<div class="wsum">{sub}</div>' if sub else ""
    pill = f'<span class="pill na"><span class="pk">bonus</span>+{round(ride["tss"])}</span>' + "".join(subj_pills(ride))
    compbar = f'<div class="compbar"><span class="cl">Extra ride</span>{pill}</div>'
    tc = " today" if d == today else ""
    return (f'<div class="card{tc} extra"><div class="chead"><div class="ident">'
            f'<div class="dow">{DOW[d.weekday()]} {d.strftime("%d %b")} {iotag(ca)}</div>'
            f'<div class="wname">{html.escape(name)}</div>{sumline}</div></div>'
            f'<div class="cbody">{viz}<div class="data">{grid}</div></div>{compbar}</div>')

def wcard(day):
    d = date.fromisoformat(day["date"])
    segs = day.get("segments") or []
    typ = day.get("type", "")
    wr, other_rides = (None, []) if typ == "Walk" else assign_rides(day)
    rs = (wr["sum"] if wr else {})
    aid = wr["id"] if wr else None
    ride_name = wr["name"] if wr else None
    cls, comp, actual, adur = status_for(day)
    unplanned = day["planned_tss"] == 0 and actual > 0
    structured = bool([s for s in segs if s[0] == "ss" and seg_role(s) == "work"])
    work_segs = [(s[2]/100*FTP, s[1]) for s in segs if s[0] == "ss" and seg_role(s) == "work"]

    # Rest (planned) vs Empty (no plan), nothing ridden -> minimal header-only card
    if day["planned_tss"] == 0 and actual == 0 and typ != "Walk":
        rn = "Rest" if typ == "Rest" else "Empty"
        tc = " today" if d == today else ""
        return (f'<div class="card{tc}"><div class="rest"><div class="ident">'
                f'<div class="dow">{DOW[d.weekday()]} {d.strftime("%d %b")}</div>'
                f'<div class="rn">{rn}</div></div>{form_hero(day["date"])}<div></div></div></div>')

    header = "".join(f'<div class="h">{c}</div>' for c in COLS)
    rows = [f'<div class="h"></div>' + header]

    # plan row
    if day["planned_tss"]:
        pn = day.get("np") or np_plan(segs)
        cells = [T(fmt_dur(day["duration_s"])), T(day["planned_tss"]), T(f'{day["if"]:.2f}' if day.get("if") else "–", "" if day.get("if") else "dash"),
                 T(pn if pn else "–", "" if pn else "dash"), T(kj_plan(segs) or "–"),
                 T("–", "dash"), T("–", "dash"), T("–", "dash"), T("–", "dash"), T("–", "dash"), T("–", "dash")]
        rows.append(grid_row("Plan", cells))

    ca = None
    if actual > 0 and d <= today and aid:
        ca = compute_activity(aid, work_segs, segs)

    # actual whole-ride row
    if actual > 0 and d <= today:
        dc = " green" if day["planned_tss"] else ""  # neutral if unplanned
        rows.append(grid_row("Actual", actual_cells(adur, actual, rs, ca, dc), "act"))

    # MS row
    ms = ca["ms"] if ca else None
    if ms:
        cells = [T(fmt_dur(ms["dur"]), "blue"), T(ms["tss"], "blue"), T(f'{ms["if"]:.2f}', "blue"),
                 T(ms["np"], "blue"), T(ms["kj"], "blue"),
                 T(ms["cad"] if ms.get("cad") else "–"),
                 T(ms["hr"] if ms.get("hr") else "–", hr_class(ms.get("hr"))),
                 T(ms["ef"] if ms.get("ef") else "–"),
                 T(ms["vi"] if ms.get("vi") else "–"),
                 T(f'{ms["drift"]:+.1f}%' if ms.get("drift") is not None else "–", drift_class(ms["drift"]) if ms.get("drift") is not None else "dash"),
                 T("–", "dash")]
        rows.append(grid_row("MS", cells, "ms"))

    # sep between rows
    grid_html = ""
    for i, r in enumerate(rows):
        if i >= 2: grid_html += '<div class="sep"></div>'
        grid_html += r
    grid = f'<div class="panel"><div class="grid">{grid_html}</div></div>'

    # graphic
    if segs and structured:
        viz = f'<div class="viz">{profile_svg(segs)}</div>'
    else:
        gt = ("Unplanned ride" if unplanned else "Walk" if typ == "Walk"
              else "Unstructured" if day["planned_tss"] else "Endurance")
        viz = f'<div class="viz ghost"><div class="gi">{"🚶" if typ=="Walk" else "🚲"}</div><div class="gt">{gt}</div></div>'

    # compliance footer
    compbar = ""
    if isinstance(comp, tuple):
        tss_d, dur_d = comp
        pills = [f'<span class="pill {wc_cls(tss_d)}"><span class="pk">TSS</span>{tss_d:+.0f}%</span>',
                 f'<span class="pill {wc_cls(dur_d)}"><span class="pk">time</span>{dur_d:+.0f}%</span>']
        if ms and ms.get("score") is not None:
            sc = ms["score"]; scl = "good" if sc >= 80 else "yellow" if sc >= 70 else "orange" if sc >= 50 else "red"
            mtxt = f'{sc}%' + (f' · {ca["ms_missed"]} rep missed' if ca and ca.get("ms_missed") else "")
            pills.append(f'<span class="pill {scl}"><span class="pk">MS in-target</span>{mtxt}</span>')
        elif work_segs and ca and ca.get("attempted") is False:
            pills.append('<span class="pill na"><span class="pk">MS</span>substituted</span>')
        elif work_segs:
            pills.append('<span class="pill na"><span class="pk">MS</span>n/a</span>')
        pills += subj_pills(wr)
        compbar = f'<div class="compbar"><span class="cl">Compliance</span>{"".join(pills)}</div>'
    elif actual > 0 and d <= today and subj_pills(wr):
        compbar = f'<div class="compbar"><span class="cl">Felt</span>{"".join(subj_pills(wr))}</div>'

    # name + summary: unplanned ride overrides the plan name (e.g. "Rest")
    if unplanned:
        rname = named(ride_name)
        if rname:
            disp_name = rname; summ = "Unplanned ride"     # name = IC ride, one-liner = status
        else:
            disp_name = "Unplanned ride"; summ = ""
    else:
        disp_name = day["name"]
        summ = html.escape(day.get("summary") or day.get("details", ""))
        # substituted: workout not attempted — surface it in the one-liner
        if work_segs and actual > 0 and ca and ca.get("attempted") is False:
            summ = f"Substituted — {html.escape(named(ride_name) or 'free ride')}"
    sumline = f'<div class="wsum">{summ}</div>' if summ else ""
    # full description footer when the one-liner would truncate it
    det = day.get("details", "")
    desc_footer = f'<div class="desc">{html.escape(det)}</div>' if (not unplanned and len(det) > 62) else ""
    # card border: completed planned workout -> green/yellow/orange by DUR+TSS compliance
    # (both in -10..+20% green, one outside yellow, both outside orange); missed -> red; today -> blue
    if isinstance(comp, tuple) and day["planned_tss"]:
        outs = sum(1 for x in comp if not (-10 <= x <= 20))
        tcls = " done-green" if outs == 0 else " done-yellow" if outs == 1 else " done-orange"
    elif comp == "missed":
        tcls = " done-red"
    elif d == today:
        tcls = " today"
    else:
        tcls = ""
    primary = (f'<div class="card{tcls}"><div class="chead"><div class="ident">'
               f'<div class="dow">{DOW[d.weekday()]} {d.strftime("%d %b")} {iotag(ca)}</div>'
               f'<div class="wname">{html.escape(disp_name)}</div>{sumline}</div>'
               f'{form_hero(day["date"])}</div>'
               f'<div class="cbody">{viz}<div class="data">{grid}</div></div>{compbar}{desc_footer}</div>')
    # a second+ ride on the same day (e.g. kids ride) -> its own unplanned card below
    extras = "".join(extra_ride_card(day, r) for r in other_rides)
    return primary + extras

def wellness_strip(label):
    """Today's wellness snapshot (readiness/sleep/rMSSD/SHR-low30/weight). Reused on Week + Today."""
    if not W: return ""
    def wv(k, f=lambda x: x): return f(W[k]) if W.get(k) is not None else "—"
    l30 = (f"{round(low30_hist[W['id']])}" if W.get("id") in low30_hist
           else (f"≈{round(W['avgSleepingHR']+low30_off)}" if W.get("avgSleepingHR") is not None else "—"))
    strip = [("readiness", wv("readiness", round)), ("sleep", wv("sleepSecs", lambda x: f"{x/3600:.1f}h")),
             ("rMSSD", wv("hrv", round)), ("SHR low30", l30), ("weight", wv("weight", lambda x: f"{x:.1f}"))]
    return (f'<h2>{label}</h2><div class="wellbar">'
            + "".join(f'<div><b>{v}</b><span>{k}</span></div>' for k, v in strip) + '</div>')

def week_page(wi):
    w = weeks[wi]; m = w["monday"]; wend = m + timedelta(days=6)
    prev_url = f"../../{weeks[wi-1]['slug']}/{weeks[wi-1]['n']}/" if wi > 0 else None
    next_url = f"../../{weeks[wi+1]['slug']}/{weeks[wi+1]['n']}/" if wi < len(weeks)-1 else None
    nav = '<div class="nav">'
    nav += f'<a href="{prev_url}">← prev</a>' if prev_url else '<span>·</span>'
    if wi != cur_idx: nav += '<a href="../../current/">▶ This week</a>'
    nav += f'<a href="../../season/" class="mid">{html.escape(SEASON["title"])} · all weeks</a>'
    nav += f'<a href="{next_url}">next →</a>' if next_url else '<span>·</span>'
    nav += '</div>'
    plan_path = PLANS / f"week-{m.isoformat()}.json"
    body = HEAD.format(title=f"{w['block']} wk {w['n']}")
    body += tabbar("../../", "weeks")
    body += f'<h1>{html.escape(w["block"])} — Week {w["n"]} of {w["nweeks"]}</h1>'
    body += f'<p class="sub">{w["tag"]} · {m.strftime("%d %b")} – {wend.strftime("%d %b %Y")}</p>' + nav
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        st = [status_for(dd) for dd in plan["days"]]
        tp = sum(dd["planned_tss"] for dd in plan["days"]); td = round(sum(s[2] for s in st))
        tpd = sum(dd["duration_s"] for dd in plan["days"]); tdd = sum(s[3] for s in st)
        sp = sum(1 for dd in plan["days"] if dd["planned_tss"] > 0); sd = sum(1 for s in st if s[2] > 0)
        body += (f'<div class="statbar"><div><b>{td}/{tp}</b><span>TSS done/plan</span></div>'
                 f'<div><b>{fmt_dur(tdd)}/{fmt_dur(tpd)}</b><span>hrs done/plan</span></div>'
                 f'<div><b>{sd}/{sp}</b><span>sessions</span></div></div>')
        well_html = wellness_strip("Today — " + today.strftime("%a %d %b")) if m <= today <= wend else ""
        body += '<h2>The week</h2>'
        tstr = today.isoformat()
        for dd in plan["days"]:
            if dd["date"] == tstr:
                body += well_html  # today's snapshot, right above today's card
            body += wcard(dd)
    else:
        tag = "Off — no training" if w["off"] else "Planned — detailed closer to the date"
        body += f'<div class="blk"><div class="blkfocus">{html.escape(w["focus"])}</div><p class="sub">{tag}</p></div>'
    body += f'<p class="foot">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · MP100 · FTP {int(FTP)}W · HRmax {int(HRMAX)}</p></body></html>'
    return body

def overview():
    body = HEAD.format(title=SEASON["title"])
    body += tabbar("../", "weeks")
    body += f'<h1>{html.escape(SEASON["title"])}</h1><p class="sub">{html.escape(SEASON["goal"])}</p>'
    if cur_idx is not None:
        body += f'<div class="nav"><a href="../current/" class="mid">▶ This week — {weeks[cur_idx]["block"]} wk {weeks[cur_idx]["n"]}</a></div>'
    for b in SEASON["blocks"]:
        bw = [i for i, w in enumerate(weeks) if w["slug"] == b["slug"]]
        body += f'<div class="blk"><div class="blkhead"><span class="blktitle">{html.escape(b["title"])}</span><span class="blktag">{html.escape(b["tag"])}</span></div>'
        body += f'<div class="blkfocus">{html.escape(b["focus"])}</div><div class="wkrow">'
        for i in bw:
            w = weeks[i]; cur = " cur" if i == cur_idx else ""; off = " off" if w["off"] else ""
            body += f'<a class="wk{cur}{off}" href="../{w["slug"]}/{w["n"]}/">wk {w["n"]}<small>{w["monday"].strftime("%d %b")}</small></a>'
        body += '</div></div>'
    body += f'<p class="foot">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · MP100</p></body></html>'
    return body

def tabbar(prefix, active):
    T = [("today", "Today", "📍", prefix + "today/"),
         ("weeks", "Weeks", "🗓", prefix + "current/"),
         ("atp", "ATP", "📈", prefix + "atp/"),
         ("analytics", "Analytics", "📊", prefix + "analytics/")]
    out = '<div class="tabbar">'
    for key, label, ico, href in T:
        out += f'<a class="{"on" if key == active else ""}" href="{href}"><span class="ico">{ico}</span>{label}</a>'
    out += '</div>'
    return out

def _actual_ctl_tsb(mon):
    """End-of-week actual CTL and TSB (latest wellness in the week that is <= today)."""
    best = None
    for i in range(7):
        d = mon + timedelta(days=i)
        if d > today: break
        if d.isoformat() in wl_ct: best = wl_ct[d.isoformat()]
    if not best: return None, None
    c, a = best
    return round(c), round(c - a)

def _wk_done(mon):
    return round(sum((a.get("icu_training_load") or 0) for a in acts
                     if mon <= date.fromisoformat(a["start_date_local"][:10]) <= mon + timedelta(days=6)))

BLKCOL = {"base1": "#3f8fd8", "base2": "#2e8b3d", "base3": "#c79a1e", "peak": "#e08a3c", "taper": "#8a8a8e"}
_ATP_WD = [0.04, 0.17, 0.15, 0.18, 0.06, 0.20, 0.20]  # weekday TSS shares for CTL projection

def _plan_daily(monday):
    """{date: planned_tss} from the week's plan file, or None when no file exists (then the ramp's weekly target is used)."""
    p = ROOT / f"plans/week-{monday}.json"
    if not p.exists(): return None
    return {d["date"]: (d.get("planned_tss") or 0) for d in json.loads(p.read_text())["days"]}

def _wk_target(w):
    """Weekly planned TSS as the plan files say today (self-updating), falling back to ramp.json."""
    daily = _plan_daily(w["monday"]); return round(sum(daily.values())) if daily else w["target_tss"]

def _atp_from(c, a, from_date=None):
    """Project CTL/ATL forward from (c,a). Day by day from the plan files; days before from_date are skipped because
    the real CTL/ATL anchor already contains them. Returns [(ctl,atl)] length N+1: [0]=anchor, [k]=end of ramp week k-1."""
    pts = [(c, a)]
    for w in RAMP["weeks"]:
        mon = date.fromisoformat(w["monday"]); daily = _plan_daily(w["monday"])
        for i in range(7):
            d = mon + timedelta(days=i)
            if from_date and d < from_date: continue
            t = (daily.get(d.isoformat(), 0) if daily is not None else w["target_tss"] * _ATP_WD[i])
            c += (t - c) / 42; a += (t - a) / 7
        pts.append((c, a))
    return pts

def _atp_project():
    """ACTUAL (projected): anchored to the athlete's CURRENT REAL CTL/ATL (intervals.icu, includes everything ridden so far),
    then the plan files day by day from today (or tomorrow if today's ride is already in). Self-correcting and self-updating."""
    c = (W or {}).get("ctl"); a = (W or {}).get("atl")
    if c is None or a is None: c = float(RAMP.get("start_ctl", 44)); a = c
    rode_today = bool((by_day.get(today.isoformat()) or {}).get("rides"))
    return _atp_from(c, a, from_date=today + timedelta(days=1) if rode_today else today)

def _atp_ideal():
    """ATP PLAN: the fixed design trajectory from the plan's start CTL. Does not move."""
    c = float(RAMP.get("start_ctl", 44)); return _atp_from(c, c)

def _svg_ctl():
    wr = RAMP["weeks"]; N = len(wr)
    ideal = [c for c, a in _atp_ideal()]           # ATP plan (fixed design trajectory)
    actual = [c for c, a in _atp_project()]        # actual projected (anchored to real CTL)
    VW, VH, L, R, T, B = 920, 300, 44, 14, 18, 40
    def px(i): return L + (i / N) * (VW - L - R)    # i in 0..N (point i = end of week i-1)
    ymin, ymax = 30, 90
    def py(c): return T + (ymax - c) / (ymax - ymin) * (VH - T - B)
    p = [f'<svg viewBox="0 0 {VW} {VH}" role="img" aria-label="CTL projection to Dec 16">']
    i = 0
    while i < N:                                   # phase bands: week k spans px(k)..px(k+1)
        blk = wr[i]["block"]; j = i
        while j + 1 < N and wr[j + 1]["block"] == blk: j += 1
        x0, x1 = px(i), px(j + 1); col = BLKCOL.get(blk, "#888")
        p.append(f'<rect x="{x0:.1f}" y="{T}" width="{x1 - x0:.1f}" height="{VH - T - B}" fill="{col}" fill-opacity="0.08"/>')
        p.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{T + 12}" text-anchor="middle" font-size="11" font-weight="700" fill="{col}">{blk}</text>')
        i = j + 1
    for c in (40, 50, 60, 70, 80):                 # y grid
        y = py(c)
        p.append(f'<line x1="{L}" y1="{y:.1f}" x2="{VW - R}" y2="{y:.1f}" stroke="var(--line2)"/>')
        p.append(f'<text x="{L - 6}" y="{y + 3:.1f}" text-anchor="end" font-size="10" fill="var(--faint)">{c}</text>')
    p.append(f'<line x1="{L}" y1="{py(80):.1f}" x2="{VW - R}" y2="{py(80):.1f}" stroke="var(--accent)" stroke-width="1.3" stroke-dasharray="5 4" opacity="0.75"/>')
    apl = " ".join(f"{px(i):.1f},{py(actual[i]):.1f}" for i in range(N + 1))       # actual projected (anchored to real CTL)
    p.append(f'<polyline points="{apl}" fill="none" stroke="var(--ink)" stroke-width="2.7" stroke-linejoin="round"/>')
    ipl = " ".join(f"{px(i):.1f},{py(ideal[i]):.1f}" for i in range(N + 1))       # ATP plan (ideal) — dashed on top, stays visible when they coincide
    p.append(f'<polyline points="{ipl}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-dasharray="2 5" stroke-linecap="round" stroke-linejoin="round" opacity="0.9"/>')
    dots = [(0, actual[0])]                        # today's real CTL + any completed-week measured CTL
    for k, w in enumerate(wr):
        mon = date.fromisoformat(w["monday"]); ac, _ = _actual_ctl_tsb(mon)
        if ac is not None and mon + timedelta(days=6) <= today: dots.append((k + 1, ac))
    for i, c in dots:
        p.append(f'<circle cx="{px(i):.1f}" cy="{py(c):.1f}" r="3.5" fill="var(--ink)"/>')
    pm = None                                      # month labels at week Mondays (point k)
    for k, w in enumerate(wr):
        m = date.fromisoformat(w["monday"])
        if m.month != pm:
            p.append(f'<text x="{px(k):.1f}" y="{VH - 6}" text-anchor="middle" font-size="10" fill="var(--faint)">{m.strftime("%b")}</text>'); pm = m.month
    p.append('</svg>'); return "".join(p)

def _svg_tsb():
    wr = RAMP["weeks"]; N = len(wr); pts = _atp_project()
    VW, VH, L, R, T, B = 920, 120, 44, 14, 10, 12
    def px(i): return L + (i / N) * (VW - L - R)
    tmin, tmax = -30, 15
    def py(v): return T + (tmax - v) / (tmax - tmin) * (VH - T - B)
    bw = (VW - L - R) / N * 0.55; y0 = py(0)
    p = [f'<svg viewBox="0 0 {VW} {VH}" role="img" aria-label="planned form (TSB)">']
    for v, col in [(0, "var(--line)"), (-15, "var(--warn)"), (-25, "var(--bad)")]:
        y = py(v)
        p.append(f'<line x1="{L}" y1="{y:.1f}" x2="{VW - R}" y2="{y:.1f}" stroke="{col}" stroke-dasharray="4 3" opacity="0.6"/>')
        p.append(f'<text x="{L - 6}" y="{y + 3:.1f}" text-anchor="end" font-size="9" fill="var(--faint)">{v:+d}</text>')
    for k in range(N):                             # bar for week k = end-of-week TSB
        v = pts[k + 1][0] - pts[k + 1][1]; y = py(v); cx = (px(k) + px(k + 1)) / 2
        col = "var(--good)" if v > -5 else "var(--tempo)" if v >= -15 else "var(--mid)" if v >= -25 else "var(--bad)"
        p.append(f'<rect x="{cx - bw / 2:.1f}" y="{min(y, y0):.1f}" width="{bw:.1f}" height="{abs(y - y0):.1f}" rx="2" fill="{col}" opacity="0.8"/>')
    p.append('</svg>'); return "".join(p)

def atp_page():
    body = HEAD.format(title="ATP — " + RAMP.get("event", "Season"))
    body += tabbar("../", "atp")
    ev = date.fromisoformat(RAMP["event_day"])
    proj = _atp_project(); ideal = _atp_ideal()
    body += f'<h1>{html.escape(RAMP.get("event", "Season plan"))}</h1>'
    body += f'<p class="sub">CTL {round(proj[0][0])} today → projected {round(proj[-2][0])} by {ev.strftime("%d %b")} (target {RAMP["target_ctl"]}) · then Tenerife · <span style="color:var(--muted)">{html.escape(RAMP.get("note",""))}</span></p>'
    body += '<div class="atpwrap">' + _svg_ctl()
    body += ('<div class="leg"><span style="color:var(--ink)"><i></i>Actual CTL (projected)</span>'
             '<span style="color:var(--accent)"><i class="dash"></i>ATP plan</span>'
             '<span style="color:var(--accent)"><i class="dash"></i>Target 80</span></div>')
    body += '<div style="margin-top:6px">' + _svg_tsb() + '</div>'
    body += '<div class="leg"><span>Planned Form (TSB) — bands at −15 / −25</span></div></div>'
    seasonmap = {w["monday"].isoformat(): w for w in weeks}
    body += '<div class="atptbl"><table class="atp"><thead><tr>'
    body += ''.join(f'<th>{h}</th>' for h in ["Week", "Period", "Plan", "Done", "Ramp", "CTL plan", "CTL act", "TSB plan", "TSB act"])
    body += '</tr></thead><tbody>'
    for k, w in enumerate(RAMP["weeks"]):
        mon = date.fromisoformat(w["monday"]); wend = mon + timedelta(days=6)
        ac, at = _actual_ctl_tsb(mon); done = _wk_done(mon); now = mon <= today <= wend
        ictl = round(ideal[k + 1][0]); itsb = round(ideal[k + 1][0] - ideal[k + 1][1])   # ATP plan (fixed)
        if wend < today and ac is not None:                                              # past = measured
            actl, atsb = ac, at
        else:                                                                            # now/future = projected
            actl = round(proj[k + 1][0]); atsb = round(proj[k + 1][0] - proj[k + 1][1])
        arate = round(proj[k + 1][0] - proj[k][0])   # projected weekly CTL delta
        lbl = f'{mon.strftime("%d %b")}–{wend.strftime("%d %b")}'
        sw = seasonmap.get(w["monday"])
        if sw: lbl = f'<a href="../{sw["slug"]}/{sw["n"]}/">{lbl}</a>'
        col = BLKCOL.get(w["block"], "#888")
        chip = f'<span class="blkchip" style="color:{col};border-color:{col}">{w["block"]}</span> {w["label"]}'
        cls = ("now " if now else "") + ("down" if w["down"] else "")
        body += (f'<tr class="{cls.strip()}"><td>{lbl}</td><td>{chip}</td><td>{_wk_target(w)}</td>'
                 f'<td>{done if done else "–"}</td><td>{arate:+d}</td><td>{ictl}</td>'
                 f'<td>{actl}</td><td>{itsb:+d}</td><td>{atsb:+d}</td></tr>')
    body += '</tbody></table></div>'
    body += f'<p class="foot">Planned = our ramp.json model · actual = intervals.icu · Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p></body></html>'
    return body

def _findings():
    out = []
    f = form_for(today.isoformat())
    rw = next((w for w in RAMP["weeks"] if w["monday"] == this_monday.isoformat()), None) if RAMP else None
    if f and rw:
        ctl, _, tsb, _ = f
        diff = ctl - rw["planned_ctl"]
        if abs(diff) <= 1:
            out.append(("good", "🎯", f'Fitness <b>CTL {ctl}</b> is right on the ATP line for this week ({rw["planned_ctl"]}).'))
        elif diff < 0:
            tail = "Expected — rebuilding from the USA block." if diff >= -6 else "The ramp needs to pick up to stay on the Teide line."
            out.append(("warn", "📉", f'Fitness <b>CTL {ctl}</b>, ATP wants <b>{rw["planned_ctl"]}</b> this week — <b>{-diff} behind</b>. {tail}'))
        else:
            out.append(("good", "📈", f'Fitness <b>CTL {ctl}</b> — <b>{diff} ahead</b> of the ATP line ({rw["planned_ctl"]}).'))
        band = ("fresh" if tsb > 5 else "neutral" if tsb >= -5 else "productive" if tsb >= -15 else "caution" if tsb >= -25 else "trashed")
        if tsb >= -15:
            out.append(("good", "⚖️", f'Form <b>TSB {tsb:+d}</b> — {band}. Inside your −15 working zone.'))
        else:
            out.append((("warn" if tsb >= -25 else "bad"), "⚖️", f'Form <b>TSB {tsb:+d}</b> — {band}, past your −15 comfort. Watch it if it lingers.'))
    drops = []
    for a in acts:
        d = date.fromisoformat(a["start_date_local"][:10])
        if this_monday <= d <= today and a.get("type") != "Walk":
            ca = compute_activity(a["id"], [], [])
            if ca.get("hr_drop60"): drops.append(ca["hr_drop60"])
    if drops and max(drops) >= 35:
        out.append(("good", "❤️", f'Best 1-min HR drop this week: <b>{max(drops)} bpm</b> — strong parasympathetic reactivation.'))
    if not out:
        out.append(("good", "✅", "Nothing flagged — plan and form on track."))
    return '<div class="findings">' + "".join(
        f'<div class="finding {s}"><span class="fi">{i}</span><span class="ft">{t}</span></div>' for s, i, t in out) + '</div>'

def today_page():
    body = HEAD.format(title="Today")
    body += tabbar("../", "today")
    body += f'<h1>Today <span style="color:var(--muted);font-weight:600;font-size:16px">· {today.strftime("%a %d %b")}</span></h1>'
    plan_path = PLANS / f"week-{this_monday.isoformat()}.json"
    tday = None
    if plan_path.exists():
        tday = next((d for d in json.loads(plan_path.read_text())["days"] if d["date"] == today.isoformat()), None)
    if tday:
        body += wcard(tday)
    else:
        body += '<div class="blk"><p class="sub">No plan entry for today.</p></div>'
    body += wellness_strip("Readiness")   # same health block as the week view
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        st = [status_for(dd) for dd in plan["days"]]
        tp = sum(dd["planned_tss"] for dd in plan["days"]); td = round(sum(s[2] for s in st))
        tpd = sum(dd["duration_s"] for dd in plan["days"]); tdd = sum(s[3] for s in st)
        sp = sum(1 for dd in plan["days"] if dd["planned_tss"] > 0); sd = sum(1 for s in st if s[2] > 0)
        body += '<h2>This week</h2>'
        body += (f'<div class="statbar"><div><b>{td}/{tp}</b><span>TSS done/plan</span></div>'
                 f'<div><b>{fmt_dur(tdd)}/{fmt_dur(tpd)}</b><span>hrs done/plan</span></div>'
                 f'<div><b>{sd}/{sp}</b><span>sessions</span></div></div>')
    body += '<h2>Feedback</h2>' + _findings()
    body += f'<p class="foot">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · MP100 · FTP {int(FTP)}W</p></body></html>'
    return body

if SITE.exists(): shutil.rmtree(SITE)
SITE.mkdir(parents=True)
for wi, w in enumerate(weeks):
    dd = SITE / w["slug"] / str(w["n"]); dd.mkdir(parents=True, exist_ok=True)
    (dd / "index.html").write_text(week_page(wi))
if cur_idx is not None:
    (SITE / "current").mkdir(exist_ok=True)
    (SITE / "current" / "index.html").write_text(week_page(cur_idx).replace('href="../../', 'href="../'))
(SITE / "season").mkdir(exist_ok=True)
(SITE / "season" / "index.html").write_text(overview())
(SITE / "atp").mkdir(exist_ok=True)
(SITE / "atp" / "index.html").write_text(atp_page())
try:
    from analytics_page import analytics_pages
    for _sub, _html in analytics_pages(HEAD, tabbar, api, ROOT, today).items():
        _d = SITE / "analytics" / _sub if _sub else SITE / "analytics"
        _d.mkdir(parents=True, exist_ok=True); (_d / "index.html").write_text(_html)
except Exception as _e:
    import traceback; traceback.print_exc(); print("analytics page FAILED — rest of the site still built")
(SITE / "today").mkdir(exist_ok=True)
(SITE / "today" / "index.html").write_text(today_page())
(SITE / "index.html").write_text('<!doctype html><meta http-equiv="refresh" content="0;url=today/"><title>Training</title><a href="today/">Today</a>')
CACHE_PATH.write_text(json.dumps(CACHE, indent=0))
print(f"site built: {len(weeks)} weeks + today/atp/season, current=wk {weeks[cur_idx]['n']} {weeks[cur_idx]['slug']}")

