#!/usr/bin/env python3
"""Physiology watchman v2 — daily 09:15 on MP100 (retry 10:15 if the LLM call failed).
Reads intervals.icu wellness + rides + the plan, scores against Egor's baselines (rules R1-R5),
then asks Claude (CLI on the box, sonnet) for a coach read of TODAY'S planned session,
and posts data + analysis + alarm to Slack #cycling (never #alerts — that is for work). Icons: 🟢 fine · 🟡 watch · 🔴 act.
  watchman.py            normal run
  watchman.py --dry      compute + LLM, print, no Slack post
  watchman.py --retry    only if a retry marker exists (LLM failed at 09:15)"""
import os, json, base64, urllib.request, statistics as S, sys, subprocess, re
from pathlib import Path
from datetime import date, timedelta

for l in Path("/srv/_env/.env").read_text().splitlines():
    if "=" in l and not l.strip().startswith("#"):
        k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
auth = base64.b64encode(("API_KEY:" + os.environ["INTERVALS_API_KEY"]).encode()).decode()
HOOK = os.environ.get("SLACK_WEBHOOK_CYCLING", "")   # #cycling ONLY — #alerts is for work. No webhook -> compute, print, do not post.
CLAUDE = "/home/USER/.local/bin/claude"; MODEL = os.environ.get("WATCHMAN_MODEL", "sonnet")
ROOT = Path("/srv/data/physiology"); MARK = ROOT / "logs/watchman_retry"
CTX = Path("/srv/scrapers/physiology-engine/config/watchman_context.md")
DRY = "--dry" in sys.argv; RETRY = "--retry" in sys.argv
if RETRY and not MARK.exists(): sys.exit(0)
POSTED = ROOT / "logs/watchman_posted"                       # once per day: a manual run + the timer must not double-post
if not DRY and POSTED.exists() and POSTED.read_text().strip() == date.today().isoformat() and not RETRY:
    print("already posted today"); sys.exit(0)

def api(u):
    r = urllib.request.Request(u, headers={"Authorization": "Basic " + auth, "User-Agent": "watchman/2"})
    return json.loads(urllib.request.urlopen(r, timeout=90).read())
def med(x): x = [v for v in x if v is not None]; return S.median(x) if x else None
def f1(x): return "-" if x is None else (f"{x:.1f}" if isinstance(x, float) else str(x))

today = date.today(); yday = today - timedelta(days=1); monday = today - timedelta(days=today.weekday())
wl = api(f"https://intervals.icu/api/v1/athlete/0/wellness?oldest={today - timedelta(days=35)}&newest={today}")
W = {w["id"]: w for w in wl}; T = W.get(today.isoformat(), {}); Y = W.get(yday.isoformat(), {})
base = [w for w in wl if w["id"] < today.isoformat()][-28:]
import physio_ctx as X
from physio_ctx import low30
m_hrv, m_rhr, m_shr = med([w.get("hrv") for w in base]), med([w.get("restingHR") for w in base]), med([w.get("avgSleepingHR") for w in base])
hrv, rhr, shr = T.get("hrv"), T.get("restingHR"), T.get("avgSleepingHR")
l30, l30_est = low30(T); m_l30 = med([low30(w)[0] for w in base])
sleep = (T.get("sleepSecs") or 0) / 3600; ctl, atl = T.get("ctl"), T.get("atl")
tsb = (Y.get("ctl") - Y.get("atl")) if Y.get("ctl") is not None and Y.get("atl") is not None else None

# ---- no overnight data yet? wait for the retry slot instead of analysing an empty morning ----
NO_DATA = hrv is None and rhr is None and not sleep
if NO_DATA and not RETRY:
    MARK.parent.mkdir(parents=True, exist_ok=True); MARK.write_text(today.isoformat())
    print("no overnight readings synced yet — deferring to the retry run"); sys.exit(0)

# ---- rules ----
flags = []; level = 0
def flag(lv, txt):
    global level; level = max(level, lv); flags.append(txt)
def stressed(w): return bool(w.get("hrv") and m_hrv and w["hrv"] < 0.7*m_hrv and w.get("restingHR") and m_rhr and w["restingHR"] >= m_rhr+4)
if stressed(T):
    flag(2 if stressed(Y) else 1, ("autonomic stress 2nd day" if stressed(Y) else "autonomic dip") + f" (rMSSD {hrv} vs {m_hrv:.0f}, RHR {rhr} vs {m_rhr:.0f})")
if sleep and sleep < 6.0: flag(1, f"short sleep {sleep:.1f}h")
if shr and m_shr and shr >= m_shr+4 and (Y.get("avgSleepingHR") or 0) >= m_shr+4: flag(1, f"sleeping HR up 2 days ({shr} vs {m_shr:.0f}) — illness watch")

# ---- rides: baseline EF, last 3 rides, yesterday's HR-drop ----
acts = api(f"https://intervals.icu/api/v1/athlete/0/activities?oldest={today - timedelta(days=100)}&newest={yday}")
from physio_ctx import is_test
rides = sorted([a for a in acts if a.get("type") != "Walk" and not is_test(a)], key=lambda a: a["start_date_local"])
cache = {}
try: cache = json.loads((ROOT / "features/card_cache.json").read_text())
except Exception: pass
ef_base = med([a["icu_weighted_avg_watts"]/a["average_heartrate"] for a in rides
               if a.get("icu_weighted_avg_watts") and a.get("average_heartrate") and 180 <= (a.get("icu_average_watts") or 0) <= 215
               and (a.get("icu_intensity") or 0) <= 76 and a["start_date_local"][:10] < yday.isoformat()]) or 1.48
def hrdrop(a, fetch=False):
    d = cache.get(str(a["id"]), {}).get("hr_drop60")
    if d is None and fetch:
        try:
            st = api(f"https://intervals.icu/api/v1/activity/{a['id']}/streams?types=heartrate")
            H = next((s["data"] for s in st if s["type"] == "heartrate"), None) or []
            d = max((H[i]-H[i+60] for i in range(len(H)-60) if H[i] and H[i+60] and H[i] > 30 and H[i+60] > 30), default=None)
        except Exception: pass
    return d
last3 = []
for a in rides[-3:]:
    np_, hr = a.get("icu_weighted_avg_watts"), a.get("average_heartrate"); ef = round(np_/hr, 2) if np_ and hr else None
    d = hrdrop(a, fetch=(a["start_date_local"][:10] == yday.isoformat()))
    last3.append(f"{a['start_date_local'][:10]} {a.get('name')} · {a.get('icu_training_load')} TSS · IF {round((a.get('icu_intensity') or 0)/100,2)} · EF {ef} · HR-drop {d if d is not None else '-'}" + (f" · {X.subjective(a)}" if X.subjective(a) else ""))
    if a["start_date_local"][:10] == yday.isoformat():
        steady = 180 <= (a.get("icu_average_watts") or 0) <= 215 and (a.get("icu_intensity") or 0) <= 76
        if steady and ef and ef < 0.90*ef_base: flag(1, f"EF {ef} on a steady ride (baseline {ef_base:.2f}) — HR high at fixed power")
        if (a.get("icu_intensity") or 0) >= 76 and d is not None and d < 30: flag(1, f"HR-drop {d} on a quality day (baseline ~40) — blunted recovery")
        prev = [b for b in rides if b["start_date_local"][:10] < yday.isoformat()]
        if prev:
            gap = (yday - date.fromisoformat(max(b["start_date_local"][:10] for b in prev))).days
            if gap >= 4: flag(1, f"first ride after {gap} days off — re-entry window: next 3 days Z2/easy")
ysum = last3[-1].split(" ", 1)[1] if last3 and last3[-1].startswith(yday.isoformat()) else "rest"

# ---- plan: today + tomorrow, ramp target ----
from physio_ctx import planned as _planned, spaced
def planned(d):
    x = _planned(d); return x["text"] if x else None
p_today, p_tmrw = planned(today), planned(today + timedelta(days=1))
_pt = _planned(today)
def _dash(x):
    """Dashboard-style: 'name · dur, TSS, IF' then the plain-language details line."""
    if not x.get("segments"): return f"*Today:* {x.get('details') or x.get('summary') or x.get('name') or 'rest'}"
    head = f"*Today:* {x['name']} · {round(x['duration_s']/60)}', {x['planned_tss']} TSS, IF {x.get('if') or '-'}"
    det = (x.get("details") or x.get("summary") or "").strip()
    return head + (f"\n{det}" if det else "")
today_block = _dash(_pt["raw"]) if _pt else "*Today:* rest"
ramp_ctl = None
try:
    rw = next((w for w in json.loads((ROOT / "config/ramp.json").read_text())["weeks"] if w["monday"] == monday.isoformat()), None)
    ramp_ctl = rw and rw.get("planned_ctl")
except Exception: pass
from physio_ctx import readings as _readings
notes = _readings(today)["notes"]                                  # wellness comments + 🍺 logged drinks, last 3 days
trend = " · ".join(f"{w['id'][5:]}: rMSSD {f1(w.get('hrv'))} RHR {f1(w.get('restingHR'))} sleep {f1((w.get('sleepSecs') or 0)/3600)}h"
                   for w in wl[-7:])

# ---- data line ----
icon = ["🟢", "🟡", "🔴"][level]; tsb_s = f"{tsb:+.0f}" if tsb is not None else "-"
def n0(x): return "–" if x is None else f"{x:.0f}"
yday_line = ysum if ysum == "rest" else " — ".join(ysum.split(" · ", 1)).replace(" · HR-drop", ", HR-drop") if False else ysum
if ysum != "rest":                      # "Viimsi loop · 56 TSS · IF 0.64 · EF 1.34 · HR-drop 16" -> "Viimsi loop — 56 TSS, IF 0.64, EF 1.34"
    parts = ysum.split(" · "); parts = [x for x in parts if not x.startswith("HR-drop")] if rides and (rides[-1].get("icu_intensity") or 0) < 76 else parts
    yday_line = parts[0] + " — " + ", ".join(parts[1:])
data = (f"*Morning read — {today.strftime('%a %d %b')}*\n\n"
        f"*Recovery:* rMSSD {n0(hrv)} (usual {n0(m_hrv)}) · resting HR {n0(rhr)} (usual {n0(m_rhr)}) · sleeping HR low-30 {'≈' if l30_est else ''}{n0(l30)} (usual {n0(m_l30)}) · sleep {sleep:.1f} h · readiness {n0(T.get('readiness'))}\n"
        f"*Load:* CTL {round(ctl) if ctl else '–'} · ATL {round(atl) if atl else '–'} · TSB {tsb_s}" + (f" · plan CTL ~{ramp_ctl}" if ramp_ctl else "") + "\n"
        f"*Yesterday:* {yday_line}" + (f"\n*Notes:* {notes}" if notes else ""))
if flags: data += "\n" + "\n".join(f"⚠️ {x}" for x in flags)
data += f"\n\n{today_block}"

# ---- LLM analysis (Claude CLI on the box) ----
prompt = f"""{CTX.read_text() if CTX.exists() else ''}

# TODAY {today.isoformat()} ({today.strftime('%A')})
Readings: rMSSD {hrv} (28d median {m_hrv}) · resting HR {rhr} ({m_rhr}) · sleeping HR avg {shr} ({m_shr}) · lowest-30' sleeping HR {'≈' if l30_est else ''}{l30} ({m_l30}; ≈ = estimated from the average) · sleep {sleep:.1f}h · readiness {T.get('readiness')}
Load: CTL {ctl} · ATL {atl} · TSB {tsb_s} · ramp plan says CTL ~{ramp_ctl} this week
Rule flags fired: {'; '.join(flags) if flags else 'none'} (script level: {icon})
7-day trend: {trend}
Egor's own notes (last 3 days, from intervals.icu wellness comments — weigh these: alcohol depresses rMSSD and raises sleeping HR the next night, sauna dehydrates, travel/late nights shorten sleep): {notes or 'none'}
Last rides (EF baseline on steady ~200W rides = {ef_base:.2f}; quality-day HR-drop baseline ≈ 40):
""" + "\n".join("  " + x for x in last3) + f"""
Today's PLANNED session (exact segments, do not invent): {p_today or 'none / rest'}
Tomorrow's planned: {p_tmrw or 'none'}

Answer in EXACTLY this format, ≤120 words total, plain words, no preamble:
STATE: <one sentence — what the body is telling us and why>
TODAY: <GO | MODIFY: how | SWAP→Z2 | REST> — <the physiological reason, one sentence>
ALARM: <🟢 or 🟡 or 🔴>
WATCH: <one thing to check tomorrow>"""
analysis = None
try:
    r = subprocess.run([CLAUDE, "-p", "--model", MODEL, "--dangerously-skip-permissions"], input=prompt, text=True,
                       capture_output=True, timeout=180, cwd="/tmp", env={**os.environ, "HOME": "/home/USER"})
    out = r.stdout.strip()
    if r.returncode == 0 and "TODAY:" in out: analysis = out
    else: sys.stderr.write(f"claude rc={r.returncode}: {r.stderr[:300]}\n")
except Exception as e:
    sys.stderr.write(f"claude call failed: {e}\n")

if analysis:
    m = re.search(r"ALARM:\s*(🟢|🟡|🔴)", analysis)
    if m: icon = ["🟢", "🟡", "🔴"][max(level, ["🟢", "🟡", "🔴"].index(m.group(1)))]
    shown = re.sub(r"^ALARM:.*\n?", "", analysis, flags=re.M).replace("STATE:", "*Body:*").replace("TODAY:", "*Session:*").replace("WATCH:", "*Watch:*")
    msg = f"{icon} {data}\n\n{spaced(shown)}"
    if MARK.exists(): MARK.unlink()
else:
    if RETRY: sys.exit(1)                                  # still failing at 10:15 — stay quiet, marker stays
    MARK.parent.mkdir(parents=True, exist_ok=True); MARK.write_text(today.isoformat())
    msg = f"{icon} {data}\n\n🔄 _coach analysis unavailable (Claude call failed) — data only; retry at 10:15_"
if RETRY: msg = (f"{icon} {data}\n\n{spaced(analysis)}" if NO_DATA else f"{icon} *Physio — coach read (retry)*\n\n{spaced(analysis)}")
if NO_DATA: msg = "⚪ *No overnight data synced by now* (no rMSSD / RHR / sleep in intervals.icu) — check the watch sync.\n" + msg

print(msg)
if DRY: sys.exit(0)
from physio_ctx import slack_post          # bot token if present (deletable, threadable), else the #cycling webhook
r = slack_post(msg); print("posted to #cycling" if r else "no slack target")
if r: POSTED.write_text(today.isoformat())
