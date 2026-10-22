#!/usr/bin/env python3
"""Ride debrief — runs every 15 min (after the site refresh fills card_cache). For each newly-synced
ride not yet debriefed: compare actual vs plan (compliance, MS quality, EF / HR-drop / drift vs baseline),
ask Claude for a coach debrief, post to #cycling. Each ride debriefed once (state in logs/debriefed.json).
  --dry          compute + LLM, print, don't post, don't mark
  --id <actId>   debrief one specific activity (test)"""
import sys, json
from datetime import date, timedelta
from pathlib import Path
import physio_ctx as X

DRY = "--dry" in sys.argv
ONLY = sys.argv[sys.argv.index("--id")+1] if "--id" in sys.argv else None
STATE = X.ROOT / "logs/debriefed.json"
done = set(json.loads(STATE.read_text())) if STATE.exists() else set()
cache = X.cache()
rs = X.rides(days=3)
todo = [a for a in rs if (ONLY and a["id"] == ONLY) or (not ONLY and a["id"] not in done and a["id"] in cache)]
skip = [a for a in todo if X.is_test(a) and not ONLY]
if skip and not DRY:
    done |= {a["id"] for a in skip}; STATE.parent.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(sorted(done)))
    print("skipped test files:", [a.get("name") for a in skip])
todo = [a for a in todo if a not in skip]
if not todo: sys.exit(0)
hist = X.history_block()

for a in todo:
    d = date.fromisoformat(a["start_date_local"][:10]); c = cache.get(a["id"], {})
    plan = X.planned(d); pl = plan["text"] if plan else "no planned session (unplanned / free ride)"
    comp = ""
    if plan and plan["raw"]["planned_tss"]:
        p = plan["raw"]; tss_d = ((a.get("icu_training_load") or 0) - p["planned_tss"]) / p["planned_tss"] * 100
        dur_d = ((a.get("moving_time") or 0) - p["duration_s"]) / p["duration_s"] * 100 if p.get("duration_s") else 0
        comp = f"Compliance: TSS {tss_d:+.0f}% · time {dur_d:+.0f}% vs plan."
    rd = X.readings(d); env = "indoor (trainer)" if X.is_indoor(a) else "outdoor"
    prompt = f"""{X.doctrine()}

# RIDE DEBRIEF — {d.isoformat()} ({d.strftime('%A')}) · {env} ride
PLANNED: {pl}
ACTUAL:  {X.ride_line(a, c)}
{comp}
That morning's readings: {rd['line']}
Egor's own notes (wellness comments, last 3 days): {rd.get('notes') or 'none'}
Ramp: plan CTL this week ~{X.ramp_ctl(d)[0]}
Trend context:
{hist}

Write an ANALYTICAL debrief for Egor in a coach's voice. Plain words first. Cite at most 6 numbers in total and only those that change a conclusion — never restate the feed above. Slack mrkdwn (*bold* with single asterisks, no headers, no tables). ≤180 words. EXACTLY this shape:
*In short:* <two sentences a non-specialist would follow: how the ride went and what it means>
*Went well:* <1-3 short bullets>
*Not ideal / watch:* <1-3 short bullets, or "nothing">
*Trend:* <one or two sentences placing this ride against the last 2-4 weeks, the right EF baseline for {env}, and CTL now vs before>
*Verdict:* <✅ nailed | ⚠️ partial | ❌ off-plan> — <one clause why>
*Next:* <the one implication for the next session>
Separate FACT from ASSUMPTION where it matters. No generic advice."""
    out = X.claude(prompt)
    if not out or "*Verdict:*" not in out:
        print(f"[{a['id']}] LLM failed — will retry next run"); continue
    np_ = a.get("icu_weighted_avg_watts"); pct = f"{round(np_/X.FTP*100)}%" if np_ else "-"
    hdr = (f"🚴 *{d.strftime('%a %d %b')} · {a.get('name')}* ({env}) — {round((a.get('moving_time') or 0)/60)}', NP {np_} W ({pct}), TSS {a.get('icu_training_load')}"
           + (f"  ·  plan: {plan['raw']['name']} {round(plan['raw']['duration_s']/60)}', TSS {plan['raw']['planned_tss']}" if plan else "  ·  unplanned"))
    msg = f"{hdr}\n\n{X.spaced(out)}"
    print(msg + "\n")
    if DRY: continue
    X.slack_post(msg); done.add(a["id"])
    STATE.parent.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(sorted(done)))
