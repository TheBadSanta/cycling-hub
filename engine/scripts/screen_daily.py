#!/usr/bin/env python3
"""Acute-lag daily screening: does a hard session shift next-morning wellness?

Tests same-day training load / zone minutes vs wellness 1-3 days LATER.
Also the reverse (does poor wellness predict a skipped/easy day = auto-regulation).
Primary window 2020+. Permutation baseline via day-shift. SDNN included (bug fixed here).
"""
import json, random
from pathlib import Path
from datetime import date, timedelta

random.seed(7)
F = Path("/srv/data/physiology/features")
panel = json.loads((F / "panel_daily.json").read_text())
days = sorted(d for d in panel if "2020-01-01" <= d <= "2026-05-18")
print(f"daily window: {days[0]}..{days[-1]} ({len(days)} days)")

def col(key):
    return {d: panel[d].get(key) for d in days}

def spearman(pairs):
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    n = len(pairs)
    if n < 30:
        return None, n
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v); i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j+1]] == v[order[i]]: j += 1
            for k in range(i, j+1): rk[order[k]] = (i+j)/2 + 1
            i = j + 1
        return rk
    xs, ys = zip(*pairs)
    rx, ry = rank(list(xs)), rank(list(ys))
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((a-mx)*(b-my) for a,b in zip(rx,ry))
    den = (sum((a-mx)**2 for a in rx)*sum((b-my)**2 for b in ry))**0.5
    return (num/den if den else 0.0), n

INPUTS = ["tss", "sst_s", "thr_s", "vo2_s", "dur_s"]
OUTCOMES = ["rhr", "low30", "sdnn"]  # next-morning nocturnal signals

tested, res = 0, []
idx = {d: i for i, d in enumerate(days)}
for xin in INPUTS:
    xc = col(xin)
    for yout in OUTCOMES:
        yc = col(yout)
        for lag in (1, 2, 3):
            # X on day i (a ridden day) vs delta(Y) from day i to day i+lag
            pairs = []
            for i, d in enumerate(days):
                x = xc[d]
                if not x:  # only ridden days with load
                    continue
                d_now = d
                d_lag = (date.fromisoformat(d) + timedelta(days=lag)).isoformat()
                d_pre = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
                y_pre, y_post = panel.get(d_pre, {}).get(yout), panel.get(d_lag, {}).get(yout)
                if y_pre is not None and y_post is not None:
                    pairs.append((x, y_post - y_pre))
            rho, n = spearman(pairs)
            tested += 1
            if rho is not None:
                res.append({"x": xin, "y": yout, "lag": lag, "rho": round(rho, 3), "n": n})

res.sort(key=lambda r: -abs(r["rho"]))

# permutation for top candidates: shuffle which days are "hard"
def perm_p(xin, yout, lag, obs, iters=300):
    xc = col(xin); yc_days = days
    xs_vals = [xc[d] for d in days if xc[d]]
    hits = 0
    for _ in range(iters):
        shift = random.randint(30, len(days)-30)
        shifted = {days[i]: xc[days[(i+shift) % len(days)]] for i in range(len(days))}
        pairs = []
        for d in days:
            x = shifted[d]
            if not x: continue
            d_lag = (date.fromisoformat(d)+timedelta(days=lag)).isoformat()
            d_pre = (date.fromisoformat(d)-timedelta(days=1)).isoformat()
            yp, yq = panel.get(d_pre,{}).get(yout), panel.get(d_lag,{}).get(yout)
            if yp is not None and yq is not None:
                pairs.append((x, yq-yp))
        rho, n = spearman(pairs)
        if rho is not None and abs(rho) >= abs(obs):
            hits += 1
    return round(hits/iters, 3)

print(f"\nAcute daily sweep: {tested} hypotheses")
print("top (|rho| desc), with permutation p:")
for r in res[:15]:
    r["perm_p"] = perm_p(r["x"], r["y"], r["lag"], r["rho"])
    print(f"  {r['x']:>7} -> d{r['y']:<6} lag{r['lag']}d  rho={r['rho']:+.3f} n={r['n']} p={r['perm_p']}")

(F / "screen_daily.json").write_text(json.dumps({"tested": tested, "results": res[:40]}, indent=1))
print("\nDONE")
