#!/usr/bin/env python3
"""Analyse a TrainingPeaks Virtual dual-recorded FIT: 'Trainer Power' vs 'Powermeter Power' developer fields.
Usage: dual_fit.py <file.fit> [--csv out.csv]. Prints per-bin ratio, overall ratio, regression, and 5-min steady segments."""
import sys, statistics as S
from fitparse import FitFile
f = sys.argv[1]; ff = FitFile(f); rows = []
for m in ff.get_messages("record"):
    d = {x.name: x.value for x in m.fields}
    t, tp, pm = d.get("timestamp"), d.get("Trainer Power"), d.get("Powermeter Power")
    if tp is not None and pm is not None: rows.append((t, float(tp), float(pm), d.get("cadence"), d.get("power")))
n = len(rows); print(f"{f.split('/')[-1]}: {n} records with both channels")
if not n: sys.exit()
print("  'power' (primary) equals Trainer Power in", sum(1 for r in rows if r[4] is not None and abs(r[4]-r[1]) < 0.5), "records, equals Powermeter in", sum(1 for r in rows if r[4] is not None and abs(r[4]-r[2]) < 0.5))
both = [(tp, pm) for _, tp, pm, _, _ in rows if tp >= 60 and pm >= 60]
print(f"  nonzero pairs: {len(both)} · mean trainer {S.mean(t for t,_ in both):.1f} W · mean pedals {S.mean(p for _,p in both):.1f} W · ratio pedals/trainer {S.mean(p for _,p in both)/S.mean(t for t,_ in both):.4f}")
# smoothing: 30-s rolling means (removes per-stroke ripple + latency)
def roll(v, k=30): return [sum(v[i:i+k])/k for i in range(0, len(v)-k+1)]
tp = roll([r[1] for r in rows]); pm = roll([r[2] for r in rows])
pairs = [(a, b) for a, b in zip(tp, pm) if a >= 80 and b >= 80]
print("  30-s smoothed, by trainer-power bin: bin  n  trainer  pedals  diff(W)  ratio")
for lo in range(100, 320, 20):
    sel = [(a, b) for a, b in pairs if lo <= a < lo+20]
    if len(sel) >= 60: print(f"    {lo:3d}-{lo+20:<3d} {len(sel):5d} {S.mean(a for a,_ in sel):7.1f} {S.mean(b for _,b in sel):7.1f} {S.mean(b-a for a,b in sel):+7.1f} {S.mean(b for _,b in sel)/S.mean(a for a,_ in sel):7.4f}")
xs = [a for a, _ in pairs]; ys = [b for _, b in pairs]
if len(xs) > 100:
    mx, my = S.mean(xs), S.mean(ys); sl = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / sum((x-mx)**2 for x in xs); ic = my - sl*mx
    print(f"  regression pedals = {sl:.4f} × trainer {ic:+.1f} W   (pure percentage error → intercept ≈ 0; pure offset → slope ≈ 1)")
# steady 5-min segments (trainer power sd < 8 W) → the cleanest comparison
seg = []
for i in range(0, len(rows)-300, 60):
    a = [r[1] for r in rows[i:i+300]]; b = [r[2] for r in rows[i:i+300]]
    if S.mean(a) >= 100 and S.pstdev(a) < 8: seg.append((rows[i][0].strftime("%H:%M"), S.mean(a), S.mean(b)))
if seg:
    print("  steady 5-min windows (trainer sd < 8 W):  start  trainer  pedals  diff  ratio")
    last = None
    for t, a, b in seg:
        if last and abs(a-last) < 5: continue
        print(f"    {t}  {a:6.1f}  {b:6.1f}  {b-a:+5.1f}  {b/a:.4f}"); last = a
