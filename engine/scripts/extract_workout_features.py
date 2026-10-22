#!/usr/bin/env python3
"""Deep-feature extraction over the ENTIRE fit archive (2017-2026).

Per workout, from the power/HR streams:
  - time in absolute power bands (25W bins) — FTP-agnostic; zone classification
    happens later in the panel stage against the rolling eFTP series
  - NP (30s rolling), avg/max power, avg/max HR, EF (NP/avgHR)
  - HR-power decoupling (1st vs 2nd half EF) on rides >= 40min
  - session fields (TSS, IF, kJ, sport, duration, distance)

Output: /srv/data/physiology/features/workouts.jsonl (resumable by canonical name)
"""
import json, sys
from pathlib import Path
from datetime import datetime, timezone

from fitparse import FitFile

SRC = Path("/srv/data/physiology/TheSource/fit")
OUT = Path("/srv/data/physiology/features/workouts.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)

done = set()
if OUT.exists():
    for line in OUT.open():
        try:
            done.add(json.loads(line)["file"])
        except Exception:
            pass
print(f"already extracted: {len(done)}", flush=True)

files = sorted(SRC.rglob("*.fit"))
print(f"total files: {len(files)}", flush=True)

def np30(powers):
    """Normalized power from 1s-ish samples (assumes ~1s spacing)."""
    if len(powers) < 60:
        return None
    window, s, out = 30, 0.0, []
    from collections import deque
    q = deque()
    for p in powers:
        q.append(p); s += p
        if len(q) > window:
            s -= q.popleft()
        if len(q) == window:
            out.append((s / window) ** 4)
    if not out:
        return None
    return (sum(out) / len(out)) ** 0.25

with OUT.open("a") as fout:
    for i, f in enumerate(files, 1):
        if f.name in done:
            continue
        if i % 100 == 0:
            print(f"{i}/{len(files)}", flush=True)
        try:
            fit = FitFile(str(f))
            sess = {}
            for msg in fit.get_messages("session"):
                for d in msg:
                    if d.value is not None:
                        sess[d.name] = d.value
                break
            powers, hrs = [], []
            for rec in fit.get_messages("record"):
                v = rec.get_values()
                p, h = v.get("power"), v.get("heart_rate")
                powers.append(p if isinstance(p, (int, float)) else None)
                hrs.append(h if isinstance(h, (int, float)) else None)
            pw = [p for p in powers if p is not None]
            hr = [h for h in hrs if h is not None]
            bands = {}
            for p in pw:
                b = int(p // 25) * 25
                bands[b] = bands.get(b, 0) + 1
            row = {
                "file": f.name,
                "start": str(sess.get("start_time", "")),
                "sport": str(sess.get("sport", "")),
                "sub_sport": str(sess.get("sub_sport", "")),
                "dur_s": int(sess.get("total_timer_time") or sess.get("total_elapsed_time") or len(powers) or 0),
                "dist_m": int(sess.get("total_distance") or 0),
                "tss": sess.get("training_stress_score"),
                "if_": sess.get("intensity_factor"),
                "kj": int((sess.get("total_work") or 0) / 1000) or None,
                "avg_p": round(sum(pw) / len(pw)) if pw else None,
                "max_p": max(pw) if pw else None,
                "np": round(np30(pw)) if pw else None,
                "avg_hr": round(sum(hr) / len(hr)) if hr else None,
                "max_hr": max(hr) if hr else None,
                "p_samples": len(pw),
                "bands": bands,
            }
            # EF + decoupling on rides with both streams, >=40min of power
            if pw and hr and len(pw) >= 2400:
                paired = [(p, h) for p, h in zip(powers, hrs) if p is not None and h is not None and h > 60]
                if len(paired) >= 2400:
                    half = len(paired) // 2
                    def ef(chunk):
                        mp = sum(p for p, _ in chunk) / len(chunk)
                        mh = sum(h for _, h in chunk) / len(chunk)
                        return mp / mh if mh else None
                    ef1, ef2 = ef(paired[:half]), ef(paired[half:])
                    row["ef"] = round((row["np"] or row["avg_p"]) / (sum(h for _, h in paired) / len(paired)), 3)
                    if ef1 and ef2 and ef1 > 0:
                        row["decoupling_pct"] = round((ef1 - ef2) / ef1 * 100, 2)
            fout.write(json.dumps(row) + "\n")
            fout.flush()
        except Exception as e:
            fout.write(json.dumps({"file": f.name, "error": str(e)[:120]}) + "\n")

print("DONE", flush=True)
