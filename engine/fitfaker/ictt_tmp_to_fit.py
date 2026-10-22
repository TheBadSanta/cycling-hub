#!/srv/scrapers/fitfaker/venv/bin/python
"""Rebuild a FIT activity from an icTrainer *.ictt.tmp live log (the pipe-delimited text file icTrainer writes while
a ride runs, {programData}\\<riderID>.ictt.tmp). Needed when icTrainer fails to save the ride (2026-10-11).

Format (decoded against the Oct-10 .ictt/.fit pair, 94 % 1-s power match):
  S|<local start yyyy-mm-dd HH:MM:SS.fff>|-1
  L|M<ms>                         lap (workout segment) begins at <ms>
  T|W<target W>|...|D<sec>|Target  segment target
  V|W<watt>|R<rpm>|B<bpm>|L<balance>|...|<rr,rr,..>|D<metres in this sample>|M<start ms>|E<end ms>|<reason>
  X|                              clean end
Each V sample's values hold for [ceil(M/1000), floor(E/1000)] seconds; distance is a per-sample delta.
Usage: ictt_tmp_to_fit.py <in.ictt.tmp> <out.fit> [--name "..."] [--tz +3] [--ftp 275]
Writes Garmin Edge 840 identity (manufacturer 1 / product 4062) so the file is accepted by Garmin Connect as-is.
"""
import sys, math, argparse, datetime as dt
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.sport_message import SportMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.profile_type import FileType, Sport, SubSport, Event, EventType, LapTrigger, Activity, DeviceIndex

ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--tz", type=float, default=3.0, help="local UTC offset hours of the S| line"); ap.add_argument("--ftp", type=float, default=275.0)
a = ap.parse_args()

lines = open(a.src, encoding="utf-8-sig").read().splitlines()
start_local = None; laps_ms = []; samples = []
def num(tokens, key):
    for t in tokens:
        if t.startswith(key):
            v = t[len(key):]
            try: return float(v)
            except ValueError: pass
    return None
for l in lines:
    t = l.split("|")
    if t[0] == "S": start_local = dt.datetime.strptime(t[1], "%Y-%m-%d %H:%M:%S.%f")
    elif t[0] == "L": laps_ms.append(num(t, "M"))
    elif t[0] == "V":
        M, E = num(t, "M"), num(t, "E")
        if M is None or E is None: continue
        samples.append(dict(w=num(t, "W"), rpm=num(t, "R"), bpm=num(t, "B"), d=num(t, "D") or 0.0, M=M, E=E))
assert start_local and samples, "no S line or no V samples"
t0 = (start_local - dt.timedelta(hours=a.tz)).replace(tzinfo=dt.timezone.utc)
end_s = int(round(samples[-1]["E"] / 1000.0))
n = end_s + 1
pw = [None] * n; cad = [None] * n; hr = [None] * n
for s in samples:
    for k in range(math.ceil(s["M"] / 1000.0), min(int(s["E"] // 1000), end_s) + 1):
        if s["w"] is not None and s["w"] >= 0: pw[k] = int(s["w"])
        if s["rpm"] is not None and s["rpm"] >= 0: cad[k] = int(s["rpm"])
        if s["bpm"] is not None and s["bpm"] > 0: hr[k] = int(s["bpm"])
# fill 1-s holes between samples with the previous value (sample gaps average 0.27 s)
for arr in (pw, cad, hr):
    for k in range(1, n):
        if arr[k] is None and arr[k - 1] is not None and k - 1 >= 0: arr[k] = arr[k - 1]
# cumulative distance: linear between sample end points
pts = [(0.0, 0.0)]; cum = 0.0
for s in samples: cum += s["d"]; pts.append((s["E"] / 1000.0, cum))
dist = [0.0] * n; j = 0
for k in range(n):
    while j + 1 < len(pts) and pts[j + 1][0] < k: j += 1
    if j + 1 < len(pts):
        (x0, y0), (x1, y1) = pts[j], pts[j + 1]; dist[k] = y0 + (y1 - y0) * ((k - x0) / (x1 - x0)) if x1 > x0 else y1
    else: dist[k] = pts[-1][1]
    dist[k] = min(dist[k], pts[-1][1])
spd = [None] + [max(0.0, dist[k] - dist[k - 1]) for k in range(1, n)]

def np_of(p):
    v = [x for x in p if x is not None]
    if len(v) < 30: return None
    roll = [sum(v[i:i + 30]) / 30.0 for i in range(0, len(v) - 29)]
    return round((sum(r ** 4 for r in roll) / len(roll)) ** 0.25)
def avg(x): v = [i for i in x if i is not None]; return round(sum(v) / len(v)) if v else None
def mx(x): v = [i for i in x if i is not None]; return max(v) if v else None
ms = lambda sec: round((t0 + dt.timedelta(seconds=sec)).timestamp() * 1000)

b = FitFileBuilder(auto_define=True, min_string_size=50)
fid = FileIdMessage(); fid.type = FileType.ACTIVITY; fid.manufacturer = 1; fid.product = 4062; fid.time_created = ms(0); fid.serial_number = 3933000011; b.add(fid)
fc = FileCreatorMessage(); fc.software_version = 3103; b.add(fc)
di = DeviceInfoMessage(); di.device_index = DeviceIndex.CREATOR; di.manufacturer = 1; di.product = 4062; di.software_version = 31.03; di.timestamp = ms(0); b.add(di)
ev = EventMessage(); ev.event = Event.TIMER; ev.event_type = EventType.START; ev.timestamp = ms(0); ev.event_group = 0; b.add(ev)
sp = SportMessage(); sp.sport = Sport.CYCLING; sp.sub_sport = SubSport.INDOOR_CYCLING; b.add(sp)
for k in range(n):
    r = RecordMessage(); r.timestamp = ms(k); r.distance = round(dist[k], 2)
    if pw[k] is not None: r.power = pw[k]
    if cad[k] is not None: r.cadence = cad[k]
    if hr[k] is not None: r.heart_rate = hr[k]
    if spd[k] is not None: r.speed = round(spd[k], 3); r.enhanced_speed = round(spd[k], 3)
    b.add(r)
ev2 = EventMessage(); ev2.event = Event.TIMER; ev2.event_type = EventType.STOP_ALL; ev2.timestamp = ms(end_s); ev2.event_group = 0; b.add(ev2)
bounds = sorted(set(int(round(x / 1000.0)) for x in laps_ms if x is not None)) or [0]
if bounds[0] != 0: bounds = [0] + bounds
bounds = [x for x in bounds if x < end_s] + [end_s]
laps = []
for i in range(len(bounds) - 1):
    s0, s1 = bounds[i], bounds[i + 1]; sl = slice(s0, s1)
    lp = LapMessage(); lp.message_index = i; lp.timestamp = ms(s1); lp.start_time = ms(s0); lp.event = Event.LAP; lp.event_type = EventType.STOP; lp.lap_trigger = LapTrigger.MANUAL
    lp.total_elapsed_time = float(s1 - s0); lp.total_timer_time = float(s1 - s0); lp.total_distance = round(dist[s1] - dist[s0], 2)
    lp.sport = Sport.CYCLING; lp.sub_sport = SubSport.INDOOR_CYCLING
    for attr, arr in (("avg_power", pw[sl]), ("avg_cadence", cad[sl]), ("avg_heart_rate", hr[sl])):
        v = avg(arr);
        if v is not None: setattr(lp, attr, v)
    for attr, arr in (("max_power", pw[sl]), ("max_cadence", cad[sl]), ("max_heart_rate", hr[sl])):
        v = mx(arr)
        if v is not None: setattr(lp, attr, v)
    npv = np_of(pw[sl]);
    if npv: lp.normalized_power = npv
    lp.avg_speed = round((dist[s1] - dist[s0]) / max(1, s1 - s0), 3); lp.max_speed = round(mx(spd[sl]) or 0, 3)
    b.add(lp); laps.append(lp)
NP = np_of(pw); IF = NP / a.ftp if NP else None; TSS = (end_s * NP * IF) / (a.ftp * 3600) * 100 if NP else None
se = SessionMessage(); se.message_index = 0; se.timestamp = ms(end_s); se.start_time = ms(0); se.event = Event.LAP; se.event_type = EventType.STOP
se.sport = Sport.CYCLING; se.sub_sport = SubSport.INDOOR_CYCLING; se.total_elapsed_time = float(end_s); se.total_timer_time = float(end_s)
se.total_distance = round(dist[-1], 2); se.first_lap_index = 0; se.num_laps = len(laps)
se.avg_power = avg(pw); se.max_power = mx(pw); se.avg_cadence = avg(cad); se.max_cadence = mx(cad)
if avg(hr): se.avg_heart_rate = avg(hr); se.max_heart_rate = mx(hr)
if NP: se.normalized_power = NP; se.intensity_factor = round(IF, 3); se.training_stress_score = round(TSS, 1)
se.avg_speed = round(dist[-1] / end_s, 3); se.max_speed = round(mx(spd) or 0, 3)
se.total_calories = round(sum(p for p in pw if p is not None) / 1000.0 * 1.0)   # kJ ≈ kcal for cycling
b.add(se)
ac = ActivityMessage(); ac.timestamp = ms(end_s); ac.local_timestamp = int((t0 + dt.timedelta(seconds=end_s + a.tz * 3600)).timestamp()) - 631065600  # local_date_time = raw FIT seconds; ac.num_sessions = 1
ac.type = Activity.MANUAL; ac.event = Event.ACTIVITY; ac.event_type = EventType.STOP; ac.total_timer_time = float(end_s); b.add(ac)
b.build().to_file(a.dst)
print(f"wrote {a.dst}: start {t0.isoformat()} dur {end_s}s records {n} laps {len(laps)} "
      f"avgP {avg(pw)} NP {NP} IF {IF and round(IF,3)} TSS {TSS and round(TSS,1)} avgHR {avg(hr)} maxHR {mx(hr)} avgCad {avg(cad)} dist {round(dist[-1])} m")
