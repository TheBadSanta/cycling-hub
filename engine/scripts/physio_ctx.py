#!/usr/bin/env python3
"""Shared context for the physio coach lanes (watchman / ride debrief / #cycling responder).
Gathers readings, rides (+ cached MS metrics), plan, ramp; calls Claude CLI on the box; posts to Slack."""
import os, json, base64, urllib.request, urllib.parse, statistics as S, subprocess, sys
from pathlib import Path
from datetime import date, datetime, timedelta

for l in Path("/srv/_env/.env").read_text().splitlines():
    if "=" in l and not l.strip().startswith("#"):
        k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
_auth = base64.b64encode(("API_KEY:" + os.environ["INTERVALS_API_KEY"]).encode()).decode()
ROOT = Path("/srv/data/physiology"); CFG = Path("/srv/scrapers/physiology-engine/config")
CLAUDE = "/home/USER/.local/bin/claude"; MODEL = os.environ.get("WATCHMAN_MODEL", "sonnet")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_CYCLING", ""); BOT = os.environ.get("SLACK_BOT_TOKEN_CYCLING", "")
FTP = 275.0

def api(u):
    r = urllib.request.Request(u, headers={"Authorization": "Basic " + _auth, "User-Agent": "physio/1"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read())
def med(x): x = [v for v in x if v is not None]; return S.median(x) if x else None
def f1(x): return "-" if x is None else (f"{x:.1f}" if isinstance(x, float) else str(x))
def doctrine(): p = CFG / "watchman_context.md"; return p.read_text() if p.exists() else ""

def readings(today=None):
    """Today's wellness vs 28d medians + 7d trend. Returns dict + a one-line text."""
    today = today or date.today(); yday = today - timedelta(days=1)
    wl = api(f"https://intervals.icu/api/v1/athlete/0/wellness?oldest={today - timedelta(days=35)}&newest={today}")
    W = {w["id"]: w for w in wl}; T = W.get(today.isoformat(), {}); Y = W.get(yday.isoformat(), {})
    base = [w for w in wl if w["id"] < today.isoformat()][-28:]
    m = {"hrv": med([w.get("hrv") for w in base]), "rhr": med([w.get("restingHR") for w in base]), "shr": med([w.get("avgSleepingHR") for w in base])}
    tsb = (Y.get("ctl") - Y.get("atl")) if Y.get("ctl") is not None and Y.get("atl") is not None else None
    d = {"hrv": T.get("hrv"), "rhr": T.get("restingHR"), "shr": T.get("avgSleepingHR"), "sleep": (T.get("sleepSecs") or 0)/3600,
         "ready": T.get("readiness"), "ctl": T.get("ctl"), "atl": T.get("atl"), "tsb": tsb, "med": m,
         "trend": " · ".join(f"{w['id'][5:]}: rMSSD {f1(w.get('hrv'))} RHR {f1(w.get('restingHR'))} sleep {f1((w.get('sleepSecs') or 0)/3600)}h" for w in wl[-7:])}
    notes = [f"{w['id'][5:]}: {w['comments'].strip()}" for w in wl[-3:] if (w.get("comments") or "").strip()]
    try:                                     # 🍺 logged drinks (Apple Health via Health Auto Export) for the last 3 days
        hd = json.loads((ROOT / "features/health_daily.json").read_text())
        for i in range(2, -1, -1):
            k = (today - timedelta(days=i)).isoformat(); n = (hd.get(k) or {}).get("drinks")
            if n: notes.append(f"{k[5:]}: 🍺 {n:g} drinks")
    except Exception: pass
    d["notes"] = " | ".join(notes)          # Egor's own wellness comments + logged drinks — context the numbers lack
    d["line"] = (f"rMSSD {f1(d['hrv'])} (base {f1(m['hrv'])}) · RHR {f1(d['rhr'])} ({f1(m['rhr'])}) · SHR {f1(d['shr'])} ({f1(m['shr'])}) · "
                 f"sleep {d['sleep']:.1f}h · ready {f1(d['ready'])} | CTL {round(d['ctl']) if d['ctl'] else '-'} ATL {round(d['atl']) if d['atl'] else '-'} TSB {f'{tsb:+.0f}' if tsb is not None else '-'}")
    return d

def cache():
    try: return json.loads((ROOT / "features/card_cache.json").read_text())
    except Exception: return {}

def ride_line(a, c=None):
    c = c or {}; np_, hr = a.get("icu_weighted_avg_watts"), a.get("average_heartrate")
    ef = round(np_/hr, 2) if np_ and hr else None; ms = c.get("ms") or {}
    s = (f"{a['start_date_local'][:16]} {a.get('name')} [{a.get('type')}] {round((a.get('moving_time') or 0)/60)}' · "
         f"TSS {a.get('icu_training_load')} · IF {round((a.get('icu_intensity') or 0)/100,2)} · NP {np_} · avgP {a.get('icu_average_watts')} · "
         f"HR {hr} (max {a.get('max_heartrate')}) · EF {ef} · Pw:HR drift {c.get('whole_drift')}% · 1'HR-drop {c.get('hr_drop60')}")
    if ms: s += (f"\n    MS (work only): {round((ms.get('dur') or 0)/60)}' · NP {ms.get('np')} · HR {ms.get('hr')} · EF {ms.get('ef')} · drift {ms.get('drift')}% · "
                 f"in-target {ms.get('score')}%" + (f" · reps missed {c.get('ms_missed')}" if c.get("ms_missed") else "") +
                 (f" · lap-matched ({c['lap_match']} anchors)" if c.get("lap_match") else " · profile-matched") )
    subj = subjective(a)
    if subj: s += f" · {subj}"
    if c.get("attempted") is False: s += "\n    (workout NOT attempted — free ride / substituted)"
    return s

FEEL = {1: "strong", 2: "good", 3: "normal", 4: "tired", 5: "weak"}
def subjective(a):
    """Egor's own marks on the ride in intervals.icu: RPE 1-10 and feel 1-5 (1 = strong, 5 = weak). Empty if not yet entered."""
    rpe, feel = a.get("icu_rpe"), a.get("feel")
    parts = []
    if rpe is not None: parts.append(f"RPE {rpe}/10")
    if feel is not None: parts.append(f"feel {feel}/5 ({FEEL.get(feel, '?')})")
    return " · ".join(parts)

def rides(days=7, n=None):
    today = date.today()
    acts = api(f"https://intervals.icu/api/v1/athlete/0/activities?oldest={today - timedelta(days=days)}&newest={today}")
    rs = sorted([a for a in acts if a.get("type") != "Walk"], key=lambda a: a["start_date_local"])
    return rs[-n:] if n else rs

def ef_baseline():
    today = date.today()
    acts = api(f"https://intervals.icu/api/v1/athlete/0/activities?oldest={today - timedelta(days=100)}&newest={today - timedelta(days=1)}")
    return med([a["icu_weighted_avg_watts"]/a["average_heartrate"] for a in acts if a.get("type") != "Walk" and a.get("icu_weighted_avg_watts")
                and a.get("average_heartrate") and 180 <= (a.get("icu_average_watts") or 0) <= 215 and (a.get("icu_intensity") or 0) <= 76]) or 1.48

def _tok(s):
    mins = s[1]/60; m = f"{mins:g}'" if mins >= 1 else f"{s[1]}\""
    return f"ramp {m} {s[2]}→{s[3]}%" if s[0] == "ramp" else f"{m} @{s[2]}%"

def _compress(toks):
    """Run-length compress repeated patterns: a b a b a b -> 3×(a / b)."""
    out, i, n = [], 0, len(toks)
    while i < n:
        best = None
        for k in range(1, min(6, (n - i)//2) + 1):
            r = 1
            while i + k*(r+1) <= n and toks[i:i+k] == toks[i+k*r:i+k*(r+1)]: r += 1
            if r >= 2 and (best is None or r*k > best[0]*best[1]): best = (r, k)
        if best:
            r, k = best; out.append(f"{r}×(" + " / ".join(toks[i:i+k]) + ")"); i += r*k
        else: out.append(toks[i]); i += 1
    return " · ".join(out)

def formula_parts(x):
    """[('WU', "5' @40% · ramp 3' 40→66%"), ('MS', "3×(15' @64% / 15' @68%)"), ('CD', ...)] from a plan day's segments."""
    segs = x.get("segments") or []
    parts = []
    for role, label in (("wu", "WU"), ("ms", "MS"), ("filler", "Tail"), ("cd", "CD")):
        sel = [s for s in segs if (s[-1] in ("work", "rec") if role == "ms" else s[-1] == role)]
        if sel: parts.append((label, _compress([_tok(s) for s in sel])))
    return parts

def plan_title(x):
    """'Easy Z2 undulating · 103', 75 TSS, IF 0.66' (or the summary for rest/walk days)."""
    if not x.get("segments"): return x.get("summary") or x.get("name") or "rest"
    return f"{x['name']} · {round(x['duration_s']/60)}', {x['planned_tss']} TSS, IF {x.get('if') or '-'}"

def formula(x):
    """One-line form: WU … | MS … | CD …  → 103', TSS 75, IF 0.66"""
    parts = formula_parts(x)
    if not parts: return x.get("summary", "") or "rest"
    return " | ".join(f"{l} {t}" for l, t in parts) + f"  → {round(x['duration_s']/60)}', TSS {x['planned_tss']}, IF {x.get('if') or '-'}"

def planned(d):
    m = d - timedelta(days=d.weekday()); p = ROOT / f"plans/week-{m.isoformat()}.json"
    if not p.exists(): return None
    x = next((x for x in json.loads(p.read_text())["days"] if x["date"] == d.isoformat()), None)
    if not x: return None
    return {"raw": x, "formula": formula(x), "title": plan_title(x), "lines": [f"{l} {t}" for l, t in formula_parts(x)],
            "text": f"{x['name']} — {x.get('details') or x.get('summary','')} · {formula(x)}"}

def ramp_ctl(d=None):
    d = d or date.today(); m = d - timedelta(days=d.weekday())
    try:
        w = next((w for w in json.loads((ROOT / "config/ramp.json").read_text())["weeks"] if w["monday"] == m.isoformat()), None)
        return (w or {}).get("planned_ctl"), (w or {}).get("label")
    except Exception: return None, None

def claude(prompt, timeout=180):
    r = subprocess.run([CLAUDE, "-p", "--model", MODEL, "--dangerously-skip-permissions"], input=prompt, text=True,
                       capture_output=True, timeout=timeout, cwd="/tmp", env={**os.environ, "HOME": "/home/USER"})
    if r.returncode != 0: sys.stderr.write(f"claude rc={r.returncode}: {r.stderr[:300]}\n"); return None
    return r.stdout.strip()

def slack_post(text, thread_ts=None, channel=None):
    """Bot token if present (needed for threads), else webhook."""
    if BOT:
        payload = {"channel": channel or os.environ.get("SLACK_CYCLING_CHANNEL_ID", ""), "text": text}
        if thread_ts: payload["thread_ts"] = thread_ts
        r = urllib.request.Request("https://slack.com/api/chat.postMessage", data=json.dumps(payload).encode(),
                                   headers={"Authorization": f"Bearer {BOT}", "Content-Type": "application/json"}, method="POST")
        return json.loads(urllib.request.urlopen(r, timeout=30).read())
    if not WEBHOOK: print("[no slack target]", text[:120]); return None
    r = urllib.request.Request(WEBHOOK, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(r, timeout=30); return {"ok": True}

def slack_api(method, **params):
    r = urllib.request.Request(f"https://slack.com/api/{method}?" + urllib.parse.urlencode(params), headers={"Authorization": f"Bearer {BOT}"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())

def is_test(a):
    """Calibration / sensor test files are not workouts."""
    n = (a.get("name") or "").lower()
    return ((a.get("moving_time") or 0) < 20*60 or (a.get("icu_training_load") or 0) < 10
            or any(k in n for k in ("test", "t7", "calib", "check", "assioma", "compare")))

VIRTUAL_DEVS = ("trainingpeaks virtual", "peaksware", "zwift", "ictrainer", "rouvy", "mywhoosh", "trainerroad", "kinomap", "bkool")
FP_PATH = ROOT / "features/fingerprint_cache.json"
try: _FP = json.loads(FP_PATH.read_text())
except Exception: _FP = {}

def fingerprint(aid):
    """Power fingerprint from the 1-s stream (fetched once, cached): jitter = mean |ΔP| / mean P on non-zero seconds
    (trainer-reported power ~0.001-0.01, pedal/crank-reported ~0.07-0.2), coast_h = runs of ≥3 s at 0 W per hour, zero = share of 0-W seconds."""
    key = str(aid)
    if key in _FP: return _FP[key]
    fp = None
    try:
        st = api(f"https://intervals.icu/api/v1/activity/{aid}/streams?types=watts")
        W = [w if w is not None else 0 for w in next((x["data"] for x in st if x["type"] == "watts"), [])]
        n = len(W)
        if n >= 600:
            runs = k = 0
            for w in W + [1]:
                if w == 0: k += 1
                else:
                    if k >= 3: runs += 1
                    k = 0
            nz = [w for w in W if w > 30]; d = [abs(W[t]-W[t-1]) for t in range(1, n) if W[t] > 30 and W[t-1] > 30]
            fp = {"zero": round(sum(1 for w in W if w == 0)/n, 3), "coast_h": round(runs/(n/3600), 1), "jitter": round(S.mean(d)/S.mean(nz), 4) if d and nz else None}
    except Exception: fp = None
    _FP[key] = fp
    try: FP_PATH.write_text(json.dumps(_FP))
    except Exception: pass
    return fp

def _overrides():
    try: return json.loads((CFG / "env_overrides.json").read_text())      # {"<activity id>": "outdoor"|"indoor"} — manual tagging in-house
    except Exception: return {}

def is_indoor(a):
    """Indoor/outdoor for the whole system. Order: manual override → unambiguous metadata → power fingerprint.
    Egor 2026-09-27: the Wahoo is often left on the indoor profile (no GPS) for outdoor rides, and in season the Assioma
    pedals may be on the T7 too, so neither GPS nor the power-meter name is trusted; the power shape is."""
    ov = _overrides().get(str(a.get("id")))
    if ov in ("indoor", "outdoor"): return ov == "indoor"
    dev = (a.get("device_name") or "").lower(); pm = (a.get("power_meter") or "").upper()
    if any(v in dev for v in VIRTUAL_DEVS) or "CYCPLUS" in pm: return True          # recorded by a trainer app / the T7 itself
    if a.get("start_latlng"): return False                                          # a GPS track = outdoors
    fp = fingerprint(a["id"]) if a.get("id") else None
    if fp and fp.get("jitter") is not None:
        if fp["jitter"] < 0.03: return True                                         # smooth = trainer-reported power = indoor
        return not (fp["coast_h"] >= 4.5 or fp["zero"] >= 0.015)                    # pedal-reported: coasting decides
    return bool(a.get("trainer")) or a.get("type") == "VirtualRide"                # no stream: fall back to what the recorder said

def history_block(days=150):
    """Trend context for the LLM: Z2 EF baselines by environment, last rides, CTL then/now, this week's plan vs actual."""
    today = date.today()
    acts = [a for a in api(f"https://intervals.icu/api/v1/athlete/0/activities?oldest={today - timedelta(days=days)}&newest={today}")
            if a.get("type") != "Walk" and not is_test(a)]
    acts.sort(key=lambda a: a["start_date_local"])
    def efv(a): return round(a["icu_weighted_avg_watts"]/a["average_heartrate"], 2) if a.get("icu_weighted_avg_watts") and a.get("average_heartrate") else None
    z2 = [a for a in acts if efv(a) and 165 <= a["icu_weighted_avg_watts"] <= 200 and (a.get("icu_intensity") or 0) <= 72 and (a.get("moving_time") or 0) >= 45*60]
    base = {}
    for env, sel in (("outdoor", [a for a in z2 if not is_indoor(a)]), ("indoor", [a for a in z2 if is_indoor(a)])):
        v = [efv(a) for a in sel]; base[env] = (round(S.median(v), 2), len(v)) if v else (None, 0)
    last = [f"{a['start_date_local'][5:10]} {'IN ' if is_indoor(a) else 'OUT'} {(a.get('name') or '')[:18]:18s} {round((a.get('moving_time') or 0)/60):3d}' NP {a.get('icu_weighted_avg_watts')} HR {a.get('average_heartrate')} EF {efv(a)} IF {round((a.get('icu_intensity') or 0)/100, 2)} TSS {a.get('icu_training_load')}" + (f"  {subjective(a)}" if subjective(a) else "")
            for a in acts[-12:]]
    wl = api(f"https://intervals.icu/api/v1/athlete/0/wellness?oldest={today - timedelta(days=90)}&newest={today}")
    W = {w["id"]: w for w in wl}
    def ctl(d): return round((W.get(d.isoformat(), {}).get("ctl") or 0))
    mon = today - timedelta(days=today.weekday()); p = ROOT / f"plans/week-{mon.isoformat()}.json"
    wk = ""
    if p.exists():
        days_ = json.loads(p.read_text())["days"]
        pl = sum(x["planned_tss"] for x in days_ if x["date"] <= today.isoformat()); pl_w = sum(x["planned_tss"] for x in days_)
        ac = sum((a.get("icu_training_load") or 0) for a in acts if a["start_date_local"][:10] >= mon.isoformat())
        wk = f"This week so far: planned {pl} TSS (week total {pl_w}) · actual {ac} TSS"
    return (f"Z2 EF baselines (NP 165-200, last {days}d): outdoor {base['outdoor'][0]} (n={base['outdoor'][1]}) · indoor {base['indoor'][0]} (n={base['indoor'][1]})\n"
            f"CTL: today {ctl(today)} · 4 wks ago {ctl(today - timedelta(days=28))} · 10 wks ago {ctl(today - timedelta(days=70))}\n{wk}\n"
            "Last rides (test files excluded):\n" + "\n".join("  " + x for x in last))

def spaced(text):
    """Blank line before every section label (*In short:*, *Went well:*, STATE:, TODAY: ...) so Slack blocks read apart."""
    import re as _re
    out = []
    for ln in text.splitlines():
        if out and out[-1].strip() and _re.match(r"^\s*(\*[A-Za-z][^*]{1,40}:\*|[A-Z][A-Z /-]{2,20}:)", ln): out.append("")
        out.append(ln)
    return "\n".join(out)

def low30(w):
    """Lowest-30' sleeping HR for a wellness day: real value from low30_history (Apple Health export) when present,
    else avgSleepingHR + calibrated offset. Returns (value, is_estimate) or (None, None)."""
    try:
        hist = json.loads((ROOT / "wellness/low30_history.json").read_text())
        off = json.loads((ROOT / "wellness/low30_calibration.json").read_text())["median_offset"]
    except Exception: hist, off = {}, -1.0
    if w.get("id") in hist: return hist[w["id"]], False
    if w.get("avgSleepingHR") is not None: return w["avgSleepingHR"] + off, True
    return None, None
