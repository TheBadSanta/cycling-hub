#!/usr/bin/env python3
"""Season generator — 13 weeks, week 1 = Mon 2026-09-21 → week 13 = Dec 14 (move to Tenerife Dec 16).
Rebuilt 2026-09-19 after the post-travel reload-shock episode. Rules baked in:
  re-entry after a break (Z2 first), 3:1 loaded:recovery, Riga wk3 = Mon/Tue/Sat/Sun only,
  Sat = consolidation SST ladder (85→92%, 10×5'→1×90'), Sun long Z2 grows 2:15→3:30,
  Tue = supporting SST ladder, Thu = tempo ladder, Wed = Z2 control ~75, Fri = Z1, Mon = walk.
  Clean reps > crammed. FTP 275."""
import json, sys
from pathlib import Path
from datetime import date, timedelta
from collections import deque

OUT = Path("/srv/data/physiology/plans"); OUT.mkdir(parents=True, exist_ok=True)
FTP = 275.0
SS = lambda s, p, r="filler": ["ss", s, p, r]
RAMP = lambda s, lo, hi, r="wu": ["ramp", s, lo, hi, r]
def wu_core():
    g = [SS(300,40,"wu"), RAMP(300,40,80,"wu"), SS(60,40,"wu"), RAMP(180,70,90,"wu"), SS(60,40,"wu")]
    for _ in range(3): g += [SS(60,90,"wu"), SS(60,40,"wu")]
    return g
def wu_sst(): return wu_core()[:-1] + [SS(240,40,"wu")]   # 2x(1@90+1@40)+1@90+4@40: one clean 4' valley, not 1'+3' (Egor 2026-10-14)
def cd_int(): return [RAMP(300,60,30,"cd")]
def wu_z2(t): return [SS(300,40,"wu"), RAMP(180,40,t,"wu")]
def cd_z2(t): return [RAMP(300,t,30,"cd")]
def _np(segs):
    pw = []
    for s in segs:
        if s[0] == "ss": pw += [s[2]/100*FTP]*s[1]
        else: lo, hi = s[2], s[3]; pw += [(lo+(hi-lo)*i/s[1])/100*FTP for i in range(s[1])]
    if not pw: return 0.0
    q = deque(); a = 0.0; o = []
    for x in pw:
        q.append(x); a += x
        if len(q) > 30: a -= q.popleft()
        if len(q) == 30: o.append((a/30)**4)
    return (sum(o)/len(o))**0.25 if o else sum(pw)/len(pw)
def day(name, typ, details, segs, summary=""):
    dur = sum(s[1] for s in segs) if segs else (3600 if typ == "Walk" else 0)
    np_ = if_ = None; tss = 9 if typ == "Walk" else 0
    if segs: np_ = _np(segs); if_ = round(np_/FTP, 2); tss = round((np_/FTP)**2*dur/36)
    return {"name": name, "type": typ, "planned_tss": tss, "duration_s": dur, "if": if_,
            "np": round(np_) if np_ else None, "summary": summary, "details": details, "segments": segs}

# ---- builders ----
WALK = day("Monday walk", "Walk", "Usual Monday walk, ~9 TSS (what intervals.icu actually scores it).", [], "Monday walk")
def z2(mins, pct=73, name="Z2 steady"):
    """Undulating Z2 (Egor 2026-09-19): >=2h -> 3 levels c-3/c/c+3 as a wave; shorter -> 2 levels c-2/c+2. ~15' steps."""
    n = max(3, round(mins/15)); bl = mins*60//n
    if mins >= 120: lv = [pct-3, pct, pct+3, pct]; pat = [lv[i % 4] for i in range(n)]
    elif pct >= 68: pat = ([pct-8, pct-3, pct+2] + [pct-3 if k % 2 == 0 else pct+2 for k in range(n)])[:n]   # Egor 2026-10-01: load in gently 65-70-75, then 70/75
    else: pat = [pct-2 if k % 2 == 0 else pct+2 for k in range(n)]   # easy Z2 (recovery / re-entry, centre < 68%): flat two-level wave, never dips into Z1 (Egor 2026-10-14)
    lo, hi = min(pat), max(pat)
    return day(name.replace("steady", "undulating"), "Z2",
               f"Undulating Z2 {lo}-{hi}% around {pct}% ({round(pct/100*FTP)}W), {n}×{bl//60}' steps. Erg WU/CD ramps.",
               wu_z2(pct)+[SS(bl, p, "work") for p in pat]+cd_z2(pct), f"Undulating Z2 {lo}-{hi}% · {mins}'")
WED = z2(78); WED_REC = z2(55)
FRI = day("Recovery Z1 spin", "Z1", "Easy Z1 spin at 55% (151W). Erg WU/CD ramps.",
          wu_z2(55)+[SS(2700,55,"work")]+cd_z2(55), "Recovery Z1 @ 55%")
def rest(name, txt): return day(name, "Rest", txt, [])
def tue_sst(reps, mins, pct, fill=900):
    # Egor 2026-10-14: reps > 10' get 5' valleys + 2' rec ("3' won't help to recover fully — 5' or run all the way through");
    # the Z2 tail gives up the difference so the ride stays the same length.
    val, rec = (300, 120) if mins > 10 else (180, 60)
    fill = fill - (reps-1)*(val-180) - (rec-60)
    s = wu_sst()
    for i in range(reps):
        s.append(SS(mins*60, pct, "work"))
        if i < reps-1: s.append(SS(val,40,"rec"))
    s += [SS(rec,40,"rec"), SS(fill,72,"filler")] + cd_int()
    return day(f"Sweet-spot {reps}×{mins}' @{pct}%", "SST",
               f"Classic SST warm-up, then {reps}×{mins}' at {pct}% ({round(pct/100*FTP)}W), {val//60}' valleys, {rec//60}' rec then Z2 tail. MS = the {reps}×{mins}'.",
               s, f"{reps}×{mins}' SST @{pct}%")
def thu_tempo(blocks, pct, fill=600):
    s = wu_sst()
    for i, mn in enumerate(blocks):
        s.append(SS(mn*60, pct, "work"))
        if i < len(blocks)-1: s.append(SS(300,40,"rec"))
    s += [SS(60,40,"rec"), SS(fill,72,"filler")] + cd_int()
    lbl = "×".join(str(b) for b in blocks) if len(set(blocks)) == 1 else "+".join(str(b) for b in blocks)
    lbl = f"{len(blocks)}×{blocks[0]}'" if len(set(blocks)) == 1 else "+".join(f"{b}'" for b in blocks)
    return day(f"Tempo {lbl} @{pct}%", "Tempo",
               f"Classic SST warm-up, then {lbl} at {pct}% ({round(pct/100*FTP)}W), 5' valleys, 1' rec then Z2 tail. MS = the tempo blocks.",
               s, f"{lbl} tempo @{pct}%")
def wu_thr(): return wu_core() + [SS(180,100,"wu"), SS(240,40,"wu")]
def thu_thr(reps, mins, pct, fill=600):
    s = wu_thr()
    for i in range(reps):
        s.append(SS(mins*60, pct, "work"))
        if i < reps-1: s.append(SS(300,40,"rec"))
    s += [SS(60,40,"rec"), SS(fill,72,"filler")] + cd_int()
    return day(f"Threshold {reps}×{mins}' @{pct}%", "THR",
               f"Classic THR warm-up (3' @100% opener), then {reps}×{mins}' at {pct}% ({round(pct/100*FTP)}W), 5' valleys, 1' rec then short Z2 tail. Ceiling work. MS = the {reps}×{mins}'.",
               s, f"{reps}×{mins}' THR @{pct}%")
def sat_lad(reps, mins, pct, val):
    s = wu_sst()
    for i in range(reps):
        s.append(SS(int(mins*60), pct, "work"))
        if i < reps-1: s.append(SS(int(val*60),40,"rec"))
    s += cd_int()
    lbl = f"{reps}×{mins}'" if reps > 1 else f"1×{mins}' straight"
    return day(f"Long SST {lbl} @{pct}%", "SST",
               f"Consolidation ladder — classic SST warm-up, then {lbl} at {pct}% ({round(pct/100*FTP)}W)" + (f", {val}' valleys" if reps > 1 else "") + ", no Z2 filler. Clean reps > crammed.",
               s, f"{lbl} @{pct}%")
def _blk(p): return [SS(840,p,"work"), SS(60,p,"filler")]
CYCLE = [65, 70, 75, 70]
def sun_long(nblk, ext_min=0, easy=False):
    """Egor's Sunday wave (2026-09-27): WU 5'@40 + 3' ramp 40→65, n×14' cycling 65/70/75/70 (two full waves at 2:15), CD 3' ramp 65→30.
    nblk=7 → 2:15 → 9 steps; nblk=8 → 2:30 → 10 steps; ext_min adds 14' steps; easy = 3% lower."""
    mins = (135 if nblk <= 7 else 150) + ext_min; n = max(3, round((mins - 11) / 14))
    pat = [(x - 3 if easy else x) for x in (CYCLE[k % 4] for k in range(n))]
    s = [SS(300,40,"wu"), RAMP(180,40,65,"wu")] + [SS(840,p,"work") for p in pat] + [RAMP(180,65,30,"cd")]
    tot = sum(x[1] for x in s); h = f"{tot//3600}:{tot%3600//60:02d}"
    return day("The Z2 Wave " + h + (" (easy)" if easy else ""), "Z2",
               f"The Z2 Wave: WU 5' @40% + ramp 3' 40-65%, then {n}×14' at {'-'.join(str(p) for p in pat)}%, CD 3' ramp 65-30%. The durability ride.",
               s, f"The Z2 Wave · {min(pat)}-{max(pat)}% · {h}")
MON_REC = day("Post-travel recovery spin", "Z1", "Easy Z1 ~30' if back in time — optional.",
              wu_z2(55)+[SS(1500,55,"work")]+cd_z2(55), "Optional · easy Z1")

# ---- the ladders, by week number (1 = Sep 21) ----
TYPE = {1:"re-entry",2:"loaded",3:"riga",4:"loaded",5:"loaded",6:"loaded",7:"recovery",
        8:"loaded",9:"loaded",10:"loaded",11:"recovery",12:"loaded",13:"move",14:"tenerife"}
TUE = {1:None,2:(3,12,88),3:(3,12,88),4:(3,14,88),5:(3,15,88),6:(3,15,89),7:None,
       8:(3,15,90),9:(3,15,91),10:(3,15,91),11:None,12:(3,15,92),13:None,14:None}   # capped at 3x15'
THU = {1:None,2:([20,20],80),3:None,4:([15,15,15],80),5:([25,25],80),6:([20,20,20],80),7:None,
       8:None,9:None,10:None,11:None,12:None,13:None,14:None}                          # tempo through wk6
THR = {8:(3,8,100),9:(3,10,100),10:(3,10,102),12:(2,15,100)}                          # threshold from wk8
SAT = {1:(9,6,86,3.5),2:(8,7,87,4),3:(7,9,88,4.5),4:(6,11,89,5),5:(5,14,90,5),6:(4,18,91,5),7:None,
       8:(3,26,92,7),9:(2,40,92,10),10:(2,44,92,10),11:None,12:(1,90,92,0),13:None,14:None}
SUN = {1:(7,0,False),2:(7,0,False),3:(7,0,False),4:(8,0,False),5:(8,0,False),6:(8,0,False),7:None,
       8:(8,30,False),9:(8,30,False),10:(8,30,False),11:None,12:(8,0,False),13:None,14:None}   # wk10 capped 3:00

def build_week(n):
    t = TYPE[n]
    tue = tue_sst(*TUE[n]) if TUE[n] else z2(75, name="Z2 steady (re-entry)") if t == "re-entry" else z2(60, 70, "Z2 easy")
    thu = thu_tempo(*THU[n]) if THU[n] else thu_thr(*THR[n]) if n in THR else (z2(75, name="Z2 steady (re-entry)") if t == "re-entry" else None)
    sat = sat_lad(*SAT[n]) if SAT[n] else None
    sun = sun_long(*SUN[n]) if SUN[n] else None
    if t == "riga":
        return [WALK, tue, rest("Riga — drive + booth setup", "4.5h drive to Riga, booth build. No ride."),
                rest("Riga — exhibition", "trade-show day. No ride."), rest("Riga — exhibition", "trade-show day. No ride."),
                sat, sun]
    if t == "move":   # Dec 14: fly Wed 16, then 3-day re-entry, first real Tenerife ride Sun
        return [WALK, z2(60, 70, "Z2 easy (pre-flight)"), rest("Fly to Tenerife", "Travel day. Dec 16."),
                z2(60, 68, "Tenerife re-entry Z2"), z2(75, 70, "Tenerife re-entry Z2"), z2(90, 70, "Tenerife re-entry Z2"),
                z2(150, 70, "Tenerife Z2 on gradient")]
    if t == "tenerife":   # Dec 21: acclimation week -> 3-day taper -> Teide Sun Dec 27
        teide = day("El Teide — the Epic Ride", "Z2", "The event. ~9.5h steady at ~64% (IF 0.62-0.66 like 2025/2026). Ride at peak.",
                    wu_z2(64)+[SS(9*3600, 64, "work")]+cd_z2(64), "The Epic Ride · ~9.5h")
        return [z2(120, 70, "Tenerife Z2 on gradient"), thu_tempo([15,15], 80, 300), z2(120, 70, "Tenerife Z2 on gradient"),
                day("Taper Z1", "Z1", "Taper day 1 — easy 45'.", wu_z2(55)+[SS(2100,55,"work")]+cd_z2(55), "Taper · easy"),
                day("Taper Z1", "Z1", "Taper day 2 (Christmas) — easy 45' or off.", wu_z2(55)+[SS(2100,55,"work")]+cd_z2(55), "Taper · easy"),
                day("Openers", "Z2", "Taper day 3 — 60' Z2 with 3×1' @100% openers.", wu_z2(70)+[SS(1500,70,"work"),SS(60,100,"work"),SS(240,70,"work"),SS(60,100,"work"),SS(240,70,"work"),SS(60,100,"work"),SS(600,70,"work")]+cd_z2(70), "Openers · 60'"),
                teide]
    if t == "recovery":
        vol = (n == 11)   # end-Nov absorber: serious load, all Z2
        lo, sa, su = (65, 180, 210) if vol else (62, 150, 150)   # absorber: Sat 3:00, Sun 3:30 (the long one, all Z2)
        return [WALK, z2(90, lo, "Low Z2 (recovery)"), z2(90, lo, "Low Z2 (recovery)"), z2(90, lo, "Low Z2 (recovery)"),
                FRI, z2(sa, 66, "Z2 long (recovery)"), z2(su, 66, "Z2 long (recovery)")]
    return [WALK, tue, WED, thu if thu else z2(75), FRI, sat, sun]

START = date(2026, 9, 21)
rows = []
for n in range(1, 15):
    mon = START + timedelta(weeks=n-1); days = build_week(n)
    plan = {"week_start": mon.isoformat(), "phase": f"Week {n} — {TYPE[n]}", "week_label": f"Week {n} ({TYPE[n]})",
            "days": [dict(d, date=(mon+timedelta(days=i)).isoformat()) for i, d in enumerate(days)]}
    if "--write" in sys.argv:
        (OUT / f"week-{mon.isoformat()}.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    tss = {d["date"]: d["planned_tss"] for d in plan["days"]}; names = [d["name"] for d in plan["days"]]
    rows.append((n, mon, TYPE[n], sum(tss.values()), names, [d["planned_tss"] for d in plan["days"]]))

# ---- formulation lines ----
def formulate(d):
    segs = d["segments"]
    if not segs: return d["name"]
    wu = sum(s[1] for s in segs if s[-1] == "wu"); cd = sum(s[1] for s in segs if s[-1] == "cd")
    work = [s for s in segs if s[-1] == "work"]; rec = [s for s in segs if s[-1] == "rec" and s[1] > 60]
    fill = [s for s in segs if s[-1] == "filler" and s[1] > 60]
    wut = "SST WU" if wu >= 1000 else "Z2 WU"
    pcts = sorted(set(s[2] for s in work)); durs = [s[1] for s in work]
    if len(pcts) > 1:
        ms = f"undulating {len(work)}×{round(sum(durs)/len(durs)/60)}' at {min(pcts)}-{max(pcts)}%"
        return f"{wut} {round(wu/60)}' · MS {ms} · CD {round(cd/60)}'. TSS {d['planned_tss']}, IF {d['if']}"
    if len(work) == 1: ms = f"{round(durs[0]/60)}' at {pcts[0]}%"
    elif len(set(durs)) == 1: ms = f"{len(work)}×{round(durs[0]/60)}' at {pcts[0]}%"
    else: ms = "+".join(f"{round(x/60)}'" for x in durs) + f" at {pcts[0]}%"
    parts = [f"{wut} {round(wu/60)}'", f"MS {ms}"]
    if rec: parts.append(f"rec {rec[0][1]/60:g}' at {rec[0][2]}%")
    parts.append(f"tail Z2 {round(sum(s[1] for s in fill)/60)}' at {fill[0][2]}%" if fill else "no tail")
    parts.append(f"CD {round(cd/60)}'")
    return " · ".join(parts) + f". TSS {d['planned_tss']}, IF {d['if']}"

DAYS = {}
for n in range(1, 15):
    DAYS[n] = build_week(n)
for di, lab in [(1,"Tue"),(3,"Thu"),(5,"Sat"),(6,"Sun")]:
    print(f"\n{lab}")
    for n in range(1, 15):
        d = DAYS[n][di]; t = TYPE[n]
        print(f"week {n:2} ({t:8}) {formulate(d)}")
print("\n=== WEEKLY ===")
for n, mon, t, tot, names, tsss in rows: print(f"  wk{n:2} {mon.strftime('%b %d')} {t:9} {tot:>4} TSS")

# ---- CTL simulation to Dec 15 (start = actual Sep 21: CTL 43 / ATL ~42) ----
ctl, atl = 43.0, 42.0; wanted = date(2026,12,15); c15 = None; c27 = None
for n, mon, t, tot, names, tsss in rows:
    for i, ts in enumerate(tsss):
        ctl += (ts-ctl)/42; atl += (ts-atl)/7
        if mon+timedelta(days=i) == wanted: c15 = ctl
        if mon+timedelta(days=i) == date(2026,12,27): c27 = ctl
    rows[n-1] = rows[n-1] + (round(ctl),)
print("\n=== CTL end of each week ===")
for r in rows: print(f"  wk{r[0]:2} {r[1].strftime('%b %d')} {r[2]:9} → CTL {r[6]}")
print(f"\n>>> CTL on Dec 15: {c15:.1f}   on Teide day Dec 27: {c27:.1f}   peak: {max(r[6] for r in rows)}")
