#!/usr/bin/env python3
"""Wide implication screening over the weekly panel (primary window 2020+).

Sweep A — lagged input->outcome: trailing Wlag-week input aggregates vs forward
  Wout-week outcome changes. Spearman on non-overlapping windows, TSS-controlled
  partials, circular-shift permutation baseline (autocorrelation-preserving).
Sweep B — episode implications: blocks (SST/THR/VO2/volume) -> outcome moves,
  with explicit counterexample enumeration (A=>B tested via !B=>!A hunt).

Honest-null design: reports how many hypotheses were tested and how many
survivors pure noise would produce (permutation). No pattern - no cues.
"""
import json, random, statistics
from pathlib import Path
from datetime import date

random.seed(42)
F = Path("/srv/data/physiology/features")
wk = json.loads((F / "panel_weekly.json").read_text())

PRIMARY_START, PRIMARY_END = "2020-01-01", "2026-05-18"
weeks = sorted(w for w in wk if PRIMARY_START <= w <= PRIMARY_END)
rows = [wk[w] for w in weeks]
N = len(rows)
print(f"primary window: {weeks[0]} .. {weeks[-1]}  ({N} weeks)")

INPUTS = ["z2_min", "tempo_min", "sst_min", "thr_min", "vo2_min", "hours", "tss", "sleep_h"]
OUTCOMES = ["ef", "low30", "rhr", "weight", "sdnn"]  # sdnn may be sparse

def series(key):
    return [r.get(key) for r in rows]

def spearman(x, y):
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(pairs)
    if n < 10:
        return None, n
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk
    xs, ys = zip(*pairs)
    rx, ry = rank(list(xs)), rank(list(ys))
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return (num / den if den else 0.0), n

def residualize(y, ctrl):
    """Return y minus linear fit on ctrl (None-safe, pairwise)."""
    pairs = [(c, v) for c, v in zip(ctrl, y) if c is not None and v is not None]
    if len(pairs) < 10:
        return y
    cs, vs = zip(*pairs)
    mc, mv = sum(cs) / len(cs), sum(vs) / len(vs)
    denom = sum((c - mc) ** 2 for c in cs)
    beta = sum((c - mc) * (v - mv) for c, v in zip(cs, vs)) / denom if denom else 0
    out = []
    for c, v in zip(ctrl, y):
        out.append(None if (c is None or v is None) else v - (mv + beta * (c - mc)))
    return out

# ---------- Sweep A ----------
def windowed(vals, wlag, wout):
    """Non-overlapping: X = mean over [i-wlag, i), dY = mean(i..i+wout) - mean(i-wout..i); step by wout."""
    xs, dys, idxs = [], [], []
    i = wlag
    while i + wout <= len(vals[0]):
        x_win = [v for v in vals[0][i - wlag:i] if v is not None]
        pre = [v for v in vals[1][max(0, i - wout):i] if v is not None]
        post = [v for v in vals[1][i:i + wout] if v is not None]
        if x_win and len(pre) >= max(1, wout // 2) and len(post) >= max(1, wout // 2):
            xs.append(sum(x_win) / len(x_win))
            dys.append(sum(post) / len(post) - sum(pre) / len(pre))
            idxs.append(i)
        else:
            xs.append(None); dys.append(None); idxs.append(i)
        i += wout
    return xs, dys

tested = 0
results = []
tss_series = series("tss")
for wlag in (3, 6):
    for wout in (2, 4):
        for xin in INPUTS:
            for yout in OUTCOMES:
                if xin == yout:
                    continue
                xs, dys = windowed([series(xin), series(yout)], wlag, wout)
                rho, n = spearman(xs, dys)
                tested += 1
                if rho is None:
                    continue
                # TSS-controlled partial (skip when input IS tss)
                rho_c = rho
                if xin != "tss":
                    txs, _ = windowed([tss_series, series(yout)], wlag, wout)
                    xr = residualize(xs, txs)
                    yr = residualize(dys, txs)
                    rho_c, _ = spearman(xr, yr)
                results.append({"x": xin, "y": yout, "wlag": wlag, "wout": wout,
                                "rho": round(rho, 3), "rho_tss_controlled": round(rho_c, 3) if rho_c is not None else None,
                                "n": n})

# permutation baseline: circular shifts of outcome series
def perm_max_rhos(xin, yout, wlag, wout, iters=200):
    base_y = series(yout)
    L = len(base_y)
    out = []
    for _ in range(iters):
        k = random.randint(26, L - 26)
        shifted = base_y[k:] + base_y[:k]
        xs, dys = windowed([series(xin), shifted], wlag, wout)
        rho, n = spearman(xs, dys)
        if rho is not None:
            out.append(abs(rho))
    return out

# empirical p for the strongest candidates only (permutation is expensive)
results.sort(key=lambda r: -abs(r.get("rho_tss_controlled") or 0))
for r in results[:25]:
    perms = perm_max_rhos(r["x"], r["y"], r["wlag"], r["wout"])
    if perms:
        p = sum(1 for v in perms if v >= abs(r["rho_tss_controlled"] or 0)) / len(perms)
        r["perm_p"] = round(p, 3)

(F / "screen_sweepA.json").write_text(json.dumps({"tested": tested, "n_weeks": N, "results": results}, indent=1))
print(f"\nSweep A: {tested} hypotheses tested")
print("top candidates (TSS-controlled, with permutation p):")
for r in results[:25]:
    print(f"  {r['x']:>10} -> d{r['y']:<7} lag{r['wlag']}w out{r['wout']}w  rho={r['rho']:+.2f} ctrl={r['rho_tss_controlled']:+.2f} n={r['n']} p={r.get('perm_p')}")

# ---------- Sweep B: episodes ----------
def pctl(vals, q):
    xs = sorted(v for v in vals if v is not None)
    return xs[int(q * (len(xs) - 1))] if xs else None

def episodes(key, thresh, min_weeks=3):
    eps, cur = [], []
    for i, r in enumerate(rows):
        v = r.get(key)
        if v is not None and v >= thresh:
            cur.append(i)
        else:
            if len(cur) >= min_weeks:
                eps.append((cur[0], cur[-1]))
            cur = []
    if len(cur) >= min_weeks:
        eps.append((cur[0], cur[-1]))
    return eps

def outcome_move(key, i0, i1, horizon=4):
    pre = [rows[i].get(key) for i in range(max(0, i0 - 3), i0)]
    post = [rows[i].get(key) for i in range(i1 + 1, min(N, i1 + 1 + horizon))]
    pre = [v for v in pre if v is not None]; post = [v for v in post if v is not None]
    if not pre or not post:
        return None
    return round(sum(post) / len(post) - sum(pre) / len(pre), 3)

print("\nSweep B: episode implications (block -> outcome move, pre-3wk vs post-4wk)")
ep_report = {}
for key in ("sst_min", "thr_min", "vo2_min", "hours"):
    th = pctl(series(key), 0.75)
    eps = episodes(key, th)
    ep_report[key] = {"threshold": th, "episodes": []}
    print(f"\n  {key} blocks (>=3wk above P75={round(th) if th else '-'}): {len(eps)}")
    for (i0, i1) in eps:
        moves = {y: outcome_move(y, i0, i1) for y in OUTCOMES}
        ep_report[key]["episodes"].append({"start": weeks[i0], "end": weeks[i1], "moves": moves})
        mv = " ".join(f"d{y}={m}" for y, m in moves.items() if m is not None)
        print(f"    {weeks[i0]}..{weeks[i1]}  {mv}")

(F / "screen_sweepB.json").write_text(json.dumps(ep_report, indent=1))
print("\nDONE")
