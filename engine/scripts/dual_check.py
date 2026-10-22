#!/usr/bin/env python3
"""Dual-recording check: mirror raw TPV FIT files from the NAS (analysis-only folder), and for every NEW file whose
'Trainer Power' and 'Powermeter Power' channels actually differ, post trainer-vs-pedals numbers to #cycling.
Runs as ExecStartPre of physio-debrief (every 15 min). State: logs/dual_checked.json. --dry = no post."""
import sys, json, subprocess, statistics as S
from pathlib import Path
from fitparse import FitFile
import physio_ctx as X
DRY = "--dry" in sys.argv
SRC = X.ROOT / "sources/tpv_raw"; SRC.mkdir(parents=True, exist_ok=True); STATE = X.ROOT / "logs/dual_checked.json"
subprocess.run(["rsync", "-a", "--rsync-path=/usr/bin/rsync", "--include=*.fit", "--exclude=*", "$NAS_SSH:/volume1/Cycling/TPVirtual_raw/", str(SRC) + "/"], capture_output=True, timeout=120)
done = set(json.loads(STATE.read_text())) if STATE.exists() else set()

def analyse(f):
    rows = []
    for m in FitFile(str(f)).get_messages("record"):
        d = {x.name: x.value for x in m.fields}
        if d.get("Trainer Power") is not None and d.get("Powermeter Power") is not None: rows.append((float(d["Trainer Power"]), float(d["Powermeter Power"])))
    if len(rows) < 600: return None
    diff = sum(1 for a, b in rows if abs(a - b) > 0.5)
    if diff < len(rows) * 0.05: return {"dual": False, "n": len(rows)}          # both channels from one device
    def roll(v, k=30): return [sum(v[i:i+k])/k for i in range(0, len(v)-k+1)]
    tp, pm = roll([a for a, _ in rows]), roll([b for _, b in rows])
    pairs = [(a, b) for a, b in zip(tp, pm) if a >= 80 and b >= 80]
    if len(pairs) < 300: return {"dual": True, "n": len(rows), "pairs": len(pairs)}
    xs, ys = [a for a, _ in pairs], [b for _, b in pairs]; mx, my = S.mean(xs), S.mean(ys)
    sl = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / sum((x-mx)**2 for x in xs); ic = my - sl*mx
    bins = []
    for lo in range(100, 320, 20):
        sel = [(a, b) for a, b in pairs if lo <= a < lo+20]
        if len(sel) >= 60: bins.append((lo, len(sel), S.mean(a for a, _ in sel), S.mean(b for _, b in sel)))
    return {"dual": True, "n": len(rows), "ratio": my/mx, "slope": sl, "intercept": ic, "bins": bins, "mean_t": mx, "mean_p": my}

for f in sorted(SRC.glob("*.fit")):
    if f.name in done: continue
    try: r = analyse(f)
    except Exception as e: print("parse failed", f.name, e); r = None
    done.add(f.name)
    if not r or not r.get("dual") or "ratio" not in r: print(f.name, "->", r); continue
    ratio = r["ratio"]; verdict = "✅ within 2%" if abs(ratio - 1) <= 0.02 else ("⚠️ within 3%" if abs(ratio - 1) <= 0.03 else "❌ off by more than 3%")
    shape = "a percentage error (intercept ≈ 0)" if abs(r["intercept"]) < 4 else f"an offset of ~{r['intercept']:+.0f} W"
    lines = [f"🔧 *Dual recording check — {f.name[:8]}… {f.name.split('_')[1][:4]}-{f.name.split('_')[1][4:6]}-{f.name.split('_')[1][6:8]}*",
             f"Pedals ÷ trainer = *{ratio:.3f}* ({(ratio-1)*100:+.1f}%) over {r['n']//60} min · {verdict} · looks like {shape}", ""]
    lines += [f"{lo}–{lo+20} W: trainer {a:.0f} · pedals {b:.0f} · {b-a:+.1f} W ({(b/a-1)*100:+.1f}%)" for lo, n, a, b in r["bins"]]
    try: coef = json.loads((X.CFG / "t7.json").read_text())["coefficient"]          # current Transmission Coefficient on the T7 (0.94 since 2026-09-20)
    except Exception: coef = 0.97
    if abs(ratio - 1) > 0.02: lines += ["", f"Suggested Transmission Coefficient: *{coef/ratio*100:.1f}%* (now {coef*100:.0f}%: displayed = flywheel ÷ {coef:.2f}; pedals ÷ trainer = {ratio:.3f} → set {coef:.2f} ÷ {ratio:.3f})"]
    if abs(ratio - 1) <= 0.02:                       # in tolerance → one quiet line; only a drift gets the full report
        lines = [f"🔧 Dual check {f.name.split('_')[1][:4]}-{f.name.split('_')[1][4:6]}-{f.name.split('_')[1][6:8]}: pedals ÷ trainer *{ratio:.3f}* ({(ratio-1)*100:+.1f}%) over {r['n']//60} min · ✅ within 2%"]
    msg = "\n".join(lines); print(msg)
    if not DRY: X.slack_post(msg)
STATE.parent.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps(sorted(done)))
