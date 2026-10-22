# Example data shapes

Real files from the production box (October 2026), trimmed where noted. They define the
contracts between the scripts.

| File | Produced by | Read by | Note |
|---|---|---|---|
| `week-plan.json` | `gen_season.py --write` | `make_site.py`, `push_week.py`, `physio_ctx.py` | One week object; only two of the seven days kept. Segment = `["ss", seconds, %FTP, role]` or `["ramp", seconds, from%, to%, role]`; role ∈ wu, work, rec, filler, cd. |
| `season.json` | by hand | `make_site.py` | Named blocks, first Monday, weeks, focus, `off` for trips. |
| `ramp.json` | by hand / recomputed from the plans | `make_site.py`, `watchman.py`, `physio_ctx.py` | Weekly targets and the planned CTL line; three of fourteen weeks kept. |
| `sat_ladder.json` | by hand | nobody (documentation input to the generator) | The Saturday consolidation ladder as agreed. |
| `card_cache-entry.json` | `make_site.py` | `watchman.py`, `ride_debrief.py`, `analytics_page.py` | Per-ride analysis: whole-ride drift, 1-minute HR drop, main-set block (`ms`), indoor/outdoor, lap-match anchors, reps missed. This is the Saturday ride that exposed the greedy lap matcher. |
