"""Analytics tab: four trailing-window charts (inline SVG, no JS) — rMSSD, lowest-30' sleeping HR, weight, EF vs CTL.
Windows agreed with Egor 2026-09-20: 7-day mean vs 60-day band (p25–p75) for HRV and SHR; 7-day vs 30-day for weight."""
import json, statistics as S, html
from datetime import date, timedelta, datetime, timezone

DAYS = 180
VW, VH, L, R, T, B = 1000, 260, 46, 46, 16, 30

def _median(v): return S.median(v) if v else None
def _pct(v, p): 
    if not v: return None
    s = sorted(v); k = (len(s)-1)*p; f = int(k); return s[f] + (s[min(f+1, len(s)-1)]-s[f])*(k-f)

def trailing(series, d, n, minn):
    v = [series[x] for x in (d - timedelta(days=i) for i in range(n)) if x in series]
    return v if len(v) >= minn else []

def _smooth(pts, tension=0.5):
    """Catmull-Rom through the points -> cubic Bézier path (passes through every point, no overshoot at the ends)."""
    if len(pts) < 3: return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    d = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for i in range(len(pts) - 1):
        p0 = pts[i-1] if i > 0 else pts[i]; p1 = pts[i]; p2 = pts[i+1]; p3 = pts[i+2] if i+2 < len(pts) else p2
        c1 = (p1[0] + (p2[0]-p0[0])*tension/3, p1[1] + (p2[1]-p0[1])*tension/3)
        c2 = (p2[0] - (p3[0]-p1[0])*tension/3, p2[1] - (p3[1]-p1[1])*tension/3)
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return "".join(d)

def svg_chart(x0, x1, y0, y1, layers, ylab="", right=None, yfmt=lambda v: f"{v:g}"):
    """layers: list of dicts {type: dots|line|band|hline|area, ...}. right: (ry0, ry1, fmt) for a right axis."""
    span = (x1 - x0).days or 1
    def px(d): return L + (d - x0).days / span * (VW - L - R)
    def py(v, lo=y0, hi=y1): return T + (hi - v) / ((hi - lo) or 1) * (VH - T - B)
    p = [f'<svg viewBox="0 0 {VW} {VH}" role="img" aria-label="{html.escape(ylab)}">']
    # y grid (5 lines)
    for i in range(5):
        v = y0 + (y1 - y0) * i / 4; y = py(v)
        p.append(f'<line x1="{L}" x2="{VW-R}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--line)" stroke-width="1"/>')
        p.append(f'<text x="{L-6}" y="{y+4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">{yfmt(v)}</text>')
        if right:
            rv = right[0] + (right[1] - right[0]) * i / 4
            p.append(f'<text x="{VW-R+6}" y="{y+4:.1f}" font-size="11" fill="var(--faint)">{right[2](rv)}</text>')
    # month ticks
    d = date(x0.year, x0.month, 1)
    while d <= x1:
        if d >= x0:
            x = px(d); p.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T}" y2="{VH-B}" stroke="var(--line2)"/>')
            p.append(f'<text x="{x+3:.1f}" y="{VH-B+16}" font-size="11" fill="var(--muted)">{d.strftime("%b")}</text>')
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    tx = px(date.today()); p.append(f'<line x1="{tx:.1f}" x2="{tx:.1f}" y1="{T}" y2="{VH-B}" stroke="var(--faint)" stroke-dasharray="2 3"/>')
    for ly in layers:
        t = ly["type"]
        if t == "band":
            pts = [(px(d), py(lo), py(hi)) for d, lo, hi in ly["pts"]]
            if pts:
                top = _smooth([(x, yh) for x, _, yh in pts]); bot = _smooth([(x, yl) for x, yl, _ in reversed(pts)])
                path = top + " L" + bot[1:] + " Z"
                p.append(f'<path d="{path}" fill="{ly.get("fill","var(--accent)")}" opacity="{ly.get("opacity",.12)}"/>')
        elif t == "area":
            lo_, hi_ = ly["range"]; pts = [(px(d), py(v, lo_, hi_)) for d, v in ly["pts"]]
            if pts:
                path = f"M{pts[0][0]:.1f},{VH-B} L" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f" L{pts[-1][0]:.1f},{VH-B} Z"
                p.append(f'<path d="{path}" fill="{ly.get("fill","var(--faint)")}" opacity="{ly.get("opacity",.15)}"/>')
        elif t == "line":
            gap = ly.get("gap_days", 10); runs, cur = [], []
            for d, v in ly["pts"]:                                   # break the line where data is missing for > gap days
                if cur and (d - cur[-1][0]).days > gap: runs.append(cur); cur = []
                cur.append((d, v))
            if cur: runs.append(cur)
            for run in runs:
                pts = [(px(d), py(v)) for d, v in run]
                if len(pts) > 1:
                    p.append(f'<path d="{_smooth(pts)}" fill="none" stroke="{ly.get("stroke","var(--accent)")}" stroke-width="{ly.get("w",2.2)}"' + (f' stroke-dasharray="{ly["dash"]}"' if ly.get("dash") else "") + ' stroke-linejoin="round" stroke-linecap="round"/>')
                elif len(pts) == 1 and ly.get("lone_dot", True):
                    p.append(f'<circle cx="{pts[0][0]:.1f}" cy="{pts[0][1]:.1f}" r="3" fill="{ly.get("stroke","var(--accent)")}"/>')
        elif t == "dots":
            for d, v in ly["pts"]:
                x, y = px(d), py(v)
                if ly.get("hollow"): p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{ly.get("r",2.6)}" fill="var(--card)" stroke="{ly.get("fill","var(--faint)")}" stroke-width="1.2"/>')
                else: p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{ly.get("r",2.6)}" fill="{ly.get("fill","var(--faint)")}" opacity="{ly.get("opacity",.8)}"/>')
        elif t == "hline":
            y = py(ly["y"]); p.append(f'<line x1="{L}" x2="{VW-R}" y1="{y:.1f}" y2="{y:.1f}" stroke="{ly.get("stroke","var(--good)")}" stroke-dasharray="6 4" stroke-width="1.5"/>')
            if ly.get("label"):
                xl, anc = ((L+4, "start") if ly.get("left") else (VW-R-4, "end"))
                p.append(f'<text x="{xl}" y="{y-5:.1f}" text-anchor="{anc}" font-size="11" fill="{ly.get("stroke","var(--good)")}">{html.escape(ly["label"])}</text>')
        elif t == "seg":
            (d0, v0), (d1, v1) = ly["pts"]
            p.append(f'<line x1="{px(d0):.1f}" y1="{py(v0):.1f}" x2="{px(d1):.1f}" y2="{py(v1):.1f}" stroke="{ly.get("stroke","var(--good)")}" stroke-dasharray="6 4" stroke-width="1.8"/>')
            if ly.get("label"): p.append(f'<text x="{px(d1)-4:.1f}" y="{py(v1)-6:.1f}" text-anchor="end" font-size="11" fill="{ly.get("stroke","var(--good)")}">{html.escape(ly["label"])}</text>')
    p.append("</svg>"); return "".join(p)

def yrange(vals, pad=0.12, floor=None):
    lo, hi = min(vals), max(vals); d = (hi - lo) or 1
    lo, hi = lo - d*pad, hi + d*pad
    if floor is not None: lo = max(lo, floor)
    return lo, hi

def card(title, sub, svg, legend):
    return (f'<div class="atpwrap"><div class="ah"><h2>{title}</h2><span class="asub">{sub}</span></div>{svg}'
            f'<div class="leg">{legend}</div></div>')

WINDOWS = [(30, "30 d"), (90, "90 d"), (180, "180 d"), (365, "1 y"), (730, "2 y")]; DEFAULT = 90
GOAL, GOAL_DAY = 80.0, date(2026, 12, 15)

def load_data(api, ROOT, today):
    """One fetch for the longest window (+70 d for trailing baselines)."""
    lo = today - timedelta(days=WINDOWS[-1][0] + 70)
    wl = api(f"https://intervals.icu/api/v1/athlete/0/wellness?oldest={lo}&newest={today}")
    acts = api(f"https://intervals.icu/api/v1/athlete/0/activities?oldest={today - timedelta(days=WINDOWS[-1][0])}&newest={today}")
    try: card = json.loads((ROOT / "features/card_cache.json").read_text())
    except Exception: card = {}
    try: hist = json.loads((ROOT / "wellness/low30_history.json").read_text()); off = json.loads((ROOT / "wellness/low30_calibration.json").read_text())["median_offset"]
    except Exception: hist, off = {}, -3.0
    return {"W": {w["id"]: w for w in wl}, "acts": acts, "card": card, "hist": hist, "off": off}

def analytics_pages(HEAD, tabbar, api, ROOT, today):
    """{'': default page, '30': ..., '90': ..., ...} — one static page per trailing window."""
    D = load_data(api, ROOT, today); out = {}
    for days, _ in WINDOWS:
        out[str(days)] = render(HEAD, tabbar, api, ROOT, today, D, days, "../../", "../")
    out[""] = render(HEAD, tabbar, api, ROOT, today, D, DEFAULT, "../", "")
    return out

def render(HEAD, tabbar, api, ROOT, today, D, DAYS, tab_prefix, sel_prefix):
    W, acts = D["W"], D["acts"]
    x0 = today - timedelta(days=DAYS); x1 = today + timedelta(days=1)
    days = [x0 + timedelta(days=i) for i in range(DAYS + 1)]
    dot_r = 2.6 if DAYS <= 180 else (2.0 if DAYS <= 365 else 1.5)
    body = HEAD.format(title="Analytics") + tabbar(tab_prefix, "analytics")
    sel = "".join(f'<a class="{"on" if d == DAYS else ""}" href="{sel_prefix}{d}/">{lbl}</a>' for d, lbl in WINDOWS)
    body += f'<div class="ah" style="justify-content:space-between"><h1>Analytics</h1><div class="winsel">{sel}</div></div>'
    body += f'<p class="sub">Trailing {DAYS} days · dots = days, line = 7-day mean, band = 60-day middle half (p25–p75)</p>'
    body += ('<style>.ah{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin:0 0 6px}.ah h2{font-size:16px;margin:0}.asub{color:var(--muted);font-size:13px}'
             '.winsel{display:flex;gap:4px}.winsel a{padding:4px 10px;border-radius:8px;font-size:12.5px;font-weight:600;color:var(--muted);border:1px solid var(--line);background:var(--card)}'
             '.winsel a.on{color:var(--card);background:var(--accent);border-color:var(--accent)}</style>')

    # ---------- 1. rMSSD ----------
    hrv = {date.fromisoformat(k): v["hrv"] for k, v in W.items() if v.get("hrv")}
    m7 = [(d, S.mean(t)) for d in days if (t := trailing(hrv, d, 7, 3))]
    band = [(d, _pct(t, .25), _pct(t, .75)) for d in days if (t := trailing(hrv, d, 60, 20))]
    med60 = [(d, _median(t)) for d in days if (t := trailing(hrv, d, 60, 20))]
    dots = [(d, v) for d, v in hrv.items() if x0 <= d <= today]
    if dots:
        lo, hi = yrange([v for _, v in dots] + [b[1] for b in band] + [b[2] for b in band], floor=0)
        cur7 = m7[-1][1] if m7 else None; b = band[-1] if band else None
        state = "" if not (cur7 and b) else (" · <b style='color:var(--warn)'>below range</b>" if cur7 < b[1] else (" · <b style='color:var(--warn)'>above range</b>" if cur7 > b[2] else " · in range"))
        sub = f"7-day <b>{cur7:.0f}</b> · 60-day median {med60[-1][1]:.0f}, range {b[1]:.0f}–{b[2]:.0f}{state}" if cur7 and b else ""
        svg = svg_chart(x0, x1, lo, hi, [{"type": "band", "pts": band}, {"type": "line", "pts": med60, "stroke": "var(--muted)", "w": 1.2, "dash": "5 4"},
                                          {"type": "dots", "pts": dots, "r": dot_r}, {"type": "line", "pts": m7}], "rMSSD", yfmt=lambda v: f"{v:.0f}")
        body += card("Sleeping HRV (rMSSD)", "ms · higher = more recovered · a single day far above the band is the post-rest trap, not readiness", svg,
                     '<span style="color:var(--accent)"><i></i>7-day mean</span><span style="color:var(--muted)"><i class="dash"></i>60-day median</span><span style="color:var(--accent);opacity:.6"><i style="border-top-width:8px;opacity:.25"></i>60-day p25–p75</span>' + (f'<span>{sub}</span>' if sub else ""))
    # ---------- 2. lowest-30 sleeping HR ----------
    hist, off = D["hist"], D["off"]
    l30, est = {}, {}
    for k, v in W.items():
        d = date.fromisoformat(k)
        if k in hist: l30[d] = hist[k]
        elif v.get("avgSleepingHR") is not None: l30[d] = v["avgSleepingHR"] + off; est[d] = True
    m7 = [(d, S.mean(t)) for d in days if (t := trailing(l30, d, 7, 3))]
    band = [(d, _pct(t, .25), _pct(t, .75)) for d in days if (t := trailing(l30, d, 60, 20))]
    med60 = [(d, _median(t)) for d in days if (t := trailing(l30, d, 60, 20))]
    real = [(d, v) for d, v in l30.items() if x0 <= d <= today and d not in est]; esti = [(d, v) for d, v in l30.items() if x0 <= d <= today and d in est]
    if real or esti:
        vals = [v for _, v in real + esti]; lo, hi = yrange(vals + [b[1] for b in band] + [b[2] for b in band])
        cur7 = m7[-1][1] if m7 else None; b = band[-1] if band else None
        state = "" if not (cur7 and b) else (" · <b style='color:var(--warn)'>above range</b>" if cur7 > b[2] else (" · <b style='color:var(--good)'>below range</b>" if cur7 < b[1] else " · in range"))
        sub = f"7-day <b>{cur7:.1f}</b> · 60-day median {med60[-1][1]:.1f}, range {b[1]:.1f}–{b[2]:.1f}{state}" if cur7 and b else ""
        svg = svg_chart(x0, x1, lo, hi, [{"type": "band", "pts": band, "fill": "var(--bad)"}, {"type": "line", "pts": med60, "stroke": "var(--muted)", "w": 1.2, "dash": "5 4"},
                                          {"type": "dots", "pts": esti, "hollow": True, "r": dot_r}, {"type": "dots", "pts": real, "r": dot_r}, {"type": "line", "pts": m7, "stroke": "var(--bad)"}], "lowest-30 sleeping HR", yfmt=lambda v: f"{v:.0f}")
        body += card("Lowest-30′ sleeping HR", "bpm · lower = better · hollow dots = estimated from the average (no raw samples that night)", svg,
                     '<span style="color:var(--bad)"><i></i>7-day mean</span><span style="color:var(--muted)"><i class="dash"></i>60-day median</span><span style="color:var(--bad);opacity:.6"><i style="border-top-width:8px;opacity:.25"></i>60-day p25–p75</span>' + (f'<span>{sub}</span>' if sub else ""))
    # ---------- 3. weight ----------
    wt = {date.fromisoformat(k): v["weight"] for k, v in W.items() if v.get("weight")}
    m7 = [(d, S.mean(t)) for d in days if (t := trailing(wt, d, 7, 3))]
    m30 = [(d, S.mean(t)) for d in days if (t := trailing(wt, d, 30, 10))]
    dots = [(d, v) for d, v in wt.items() if x0 <= d <= today]
    if dots:
        wx1 = date(2026, 12, 27); cur7 = m7[-1][1] if m7 else dots[-1][1]
        lo, hi = yrange([v for _, v in dots] + [GOAL], pad=0.08)
        wk = (GOAL_DAY - today).days / 7; rate = (cur7 - GOAL) / wk if wk > 0 else 0
        m30v = m30[-1][1] if m30 else None
        sub = f"7-day <b>{cur7:.1f} kg</b>" + (f" · 30-day {m30v:.1f}" if m30v else "") + f" · to {GOAL:.0f} kg by {GOAL_DAY.strftime('%d %b')}: {cur7-GOAL:.1f} kg in {wk:.0f} wks = <b>{rate:.2f} kg/wk</b>"
        svg = svg_chart(x0, wx1, lo, hi, [{"type": "dots", "pts": dots, "r": dot_r}, {"type": "line", "pts": m30, "stroke": "var(--muted)", "w": 1.4, "dash": "5 4"},
                                           {"type": "line", "pts": m7}, {"type": "seg", "pts": [(today, cur7), (GOAL_DAY, GOAL)], "label": f"{GOAL:.0f} kg · {GOAL_DAY.strftime('%d %b')}"}],
                        "weight", yfmt=lambda v: f"{v:.0f}")
        body += card("Weight", "kg · 7-day vs 30-day mean · dashed green = the line to the target", svg,
                     f'<span style="color:var(--accent)"><i></i>7-day mean</span><span style="color:var(--muted)"><i class="dash"></i>30-day mean</span><span style="color:var(--good)"><i class="dash"></i>target</span><span>{sub}</span>')
    # ---------- 4 + 5. EF and decoupling on the MAIN SET of steady Z2 rides ----------
    import core_metrics as CM
    CARD = D["card"]
    from physio_ctx import is_indoor as indoor        # one rule for the whole system (pedals-outdoor, overrides, virtual devices)
    z2 = sorted([a for a in acts if CM.is_z2(a) and a["start_date_local"][:10] >= x0.isoformat()], key=lambda a: a["start_date_local"])
    ef_pts = {"out": [], "in": []}; dr_pts = {"out": [], "in": []}; pending = 0
    for a in z2:
        ef, dr, src = CM.ms_metrics(api, a, CARD.get(a["id"]))
        if src == "pending": pending += 1; continue
        d = date.fromisoformat(a["start_date_local"][:10]); env = "in" if indoor(a) else "out"
        if ef: ef_pts[env].append((d, ef))
        if dr is not None: dr_pts[env].append((d, dr))
    CM.save()
    def trail5(series, window=45):
        """Median of up to the last 5 rides, but only rides within `window` days — a ride after a long gap starts fresh."""
        out = []
        for i in range(len(series)):
            recent = [v for d, v in series[max(0, i-4):i+1] if (series[i][0] - d).days <= window]
            if len(recent) >= 2: out.append((series[i][0], _median(recent)))
        return out
    ctl = [(date.fromisoformat(k), v["ctl"]) for k, v in sorted(W.items()) if v.get("ctl") is not None and x0 <= date.fromisoformat(k) <= today]
    note = f" · {pending} older rides still being computed, they appear on the next refresh" if pending else ""
    if ef_pts["out"] or ef_pts["in"]:
        vals = [v for s in ef_pts.values() for _, v in s]; lo, hi = yrange(vals, pad=0.1)
        cmax = max(v for _, v in ctl) * 1.15 if ctl else 100
        tout, tin = trail5(ef_pts["out"]), trail5(ef_pts["in"])
        sub = " · ".join(x for x in [f"outdoor now <b>{tout[-1][1]:.2f}</b>" if tout else "", f"indoor now <b>{tin[-1][1]:.2f}</b>" if tin else "", f"CTL {ctl[-1][1]:.0f}" if ctl else ""] if x)
        svg = svg_chart(x0, x1, lo, hi, [{"type": "area", "pts": ctl, "range": (0, cmax)},
                                          {"type": "dots", "pts": ef_pts["in"], "fill": "var(--ink)", "opacity": .55}, {"type": "dots", "pts": ef_pts["out"], "fill": "var(--accent)"},
                                          {"type": "line", "pts": tin, "stroke": "var(--ink)", "w": 1.8, "gap_days": 21}, {"type": "line", "pts": tout, "gap_days": 21}],
                        "EF", right=(0, cmax, lambda v: f"{v:.0f}"), yfmt=lambda v: f"{v:.2f}")
        body += card("Aerobic efficiency — main set of Z2 rides", f"EF = NP ÷ HR on the main set only (WU/CD trimmed) · steady Z2 rides: ≥45′, IF ≤ 0.72, NP 150–215 W · outdoor and indoor apart · grey = CTL, right axis{note}", svg,
                     f'<span style="color:var(--accent)"><i></i>outdoor (5-ride median)</span><span style="color:var(--ink)"><i></i>indoor (5-ride median)</span><span style="color:var(--faint)"><i style="border-top-width:8px;opacity:.4"></i>CTL</span><span>{sub}</span>')
    if dr_pts["out"] or dr_pts["in"]:
        lo, hi = -8.0, 12.0                                    # clamp: a few outlier rides (±20%) must not flatten the useful band
        for env in dr_pts: dr_pts[env] = [(d, max(lo+0.3, min(hi-0.3, v))) for d, v in dr_pts[env]]
        tout, tin = trail5(dr_pts["out"]), trail5(dr_pts["in"])
        sub = " · ".join(x for x in [f"outdoor now <b>{tout[-1][1]:+.1f}%</b>" if tout else "", f"indoor now <b>{tin[-1][1]:+.1f}%</b>" if tin else ""] if x)
        svg = svg_chart(x0, x1, lo, hi, [{"type": "hline", "y": 3, "stroke": "var(--warn)", "label": "3% — watch", "left": True}, {"type": "hline", "y": 5, "stroke": "var(--bad)", "label": "5% — fatigue / heat / dehydration"},
                                          {"type": "dots", "pts": dr_pts["in"], "fill": "var(--ink)", "opacity": .55}, {"type": "dots", "pts": dr_pts["out"], "fill": "var(--accent)"},
                                          {"type": "line", "pts": tin, "stroke": "var(--ink)", "w": 1.8, "gap_days": 21}, {"type": "line", "pts": tout, "gap_days": 21}],
                        "decoupling", yfmt=lambda v: f"{v:+.0f}%")
        body += card("Aerobic decoupling — main set of Z2 rides", "Pw:HR drift = EF first half vs second half of the main set · below 3% = durable · negative = HR settling · same rides as above", svg,
                     f'<span style="color:var(--accent)"><i></i>outdoor (5-ride median)</span><span style="color:var(--ink)"><i></i>indoor (5-ride median)</span><span>{sub}</span>')
    body += f'<p class="foot">Sources: intervals.icu wellness + activities · lowest-30′ from Apple Health exports (Health Auto Export) · Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p></body></html>'
    return body
