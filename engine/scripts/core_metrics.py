"""Main-set ("core") metrics for steady Z2 rides, for the Analytics tab.
Priority: the ride card's MS metrics (card_cache, plan-matched) — else compute from the stream with WU/CD trimmed
(first 12', last 6') and cache in features/core_cache.json. EF = NP/HR on the core; drift = first-half vs second-half EF."""
import json, urllib.request, base64, os
from pathlib import Path

ROOT = Path("/srv/data/physiology"); CC = ROOT / "features/core_cache.json"; TRIM_HEAD, TRIM_TAIL = 12*60, 6*60
_cache = json.loads(CC.read_text()) if CC.exists() else {}

def is_z2(a):
    """Steady endurance ride: ≥45', IF ≤ 0.72, NP 150–215 W, not a test file."""
    return (a.get("type") != "Walk" and (a.get("moving_time") or 0) >= 45*60 and (a.get("icu_intensity") or 0) <= 72
            and a.get("icu_weighted_avg_watts") and 150 <= a["icu_weighted_avg_watts"] <= 215 and a.get("average_heartrate")
            and (a.get("icu_training_load") or 0) >= 20)

def _np(w):
    if len(w) < 30: return sum(w)/len(w) if w else 0
    r = [sum(w[i:i+30])/30 for i in range(0, len(w)-29)]; return (sum(x**4 for x in r)/len(r)) ** 0.25

def _ef(w, h):
    pairs = [(x, y) for x, y in zip(w, h) if x is not None and y and y > 30]
    if len(pairs) < 300: return None
    return _np([x for x, _ in pairs]) / (sum(y for _, y in pairs)/len(pairs))

def core_from_stream(api, aid):
    key = str(aid)
    if key in _cache: return _cache[key]
    out = None
    try:
        st = api(f"https://intervals.icu/api/v1/activity/{aid}/streams?types=watts,heartrate")
        S = {s["type"]: s["data"] for s in st}; w, h = S.get("watts"), S.get("heartrate")
        if w and h:
            n = min(len(w), len(h)); w, h = w[TRIM_HEAD:n-TRIM_TAIL], h[TRIM_HEAD:n-TRIM_TAIL]
            if len(w) >= 20*60:
                ef = _ef(w, h); m = len(w)//2; e1, e2 = _ef(w[:m], h[:m]), _ef(w[m:], h[m:])
                out = {"ef": round(ef, 3) if ef else None, "drift": round((e1-e2)/e1*100, 1) if e1 and e2 else None, "dur": len(w), "src": "core"}
    except Exception: out = None
    _cache[key] = out or {"ef": None, "drift": None, "src": "none"}
    return _cache[key]

def save(): CC.write_text(json.dumps(_cache))

def ms_metrics(api, a, card, max_new=[40]):
    """(ef, drift, src) for a ride: card MS if present, else core-from-stream (bounded number of new fetches per build)."""
    c = (card or {}).get("ms") or {}
    if c.get("ef"): return c["ef"], c.get("drift"), "ms"
    key = str(a["id"])
    if key not in _cache:
        if max_new[0] <= 0: return None, None, "pending"
        max_new[0] -= 1
    r = core_from_stream(api, a["id"]); return r.get("ef"), r.get("drift"), r.get("src")
