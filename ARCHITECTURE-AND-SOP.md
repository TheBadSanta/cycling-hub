# Physiology Engine — Architecture and Standard Operating Procedures

*A personal AI training backend for one endurance athlete. Written October 2026 from a system
that has been in daily use since July 2026. Author: Egor Pravilov with Claude.*

---

## 0. How to use this file with your Claude

This document is meant to be executed, not only read. Give it to Claude (paste it, attach it, or
point Claude at this repository) and say: **"Build this for me."** Claude should then do three
things in order.

1. **Ask the onboarding questions** in Appendix A, in one batch, and wait for the answers.
   Everything else depends on them. Do not start building on guesses.
2. **Build in the order of the sections**: history first (section 2), then the backend
   (section 3), then describe the athlete (section 4), then the plan (section 5), then the
   feedback loop (section 6). Each section ends with a "Definition of done" so Claude can report
   honestly what runs and what does not.
3. **Adapt, do not copy blindly.** The code in `engine/` is one athlete's production code. Hosts,
   folder ids and the doctrine file are specific to him. The placeholder table in section 9 lists
   what must change. The ideas in section 1 are the part that should survive unchanged.

Two rules for the Claude that builds this, learned the hard way:

- **Separate fact from assumption in every report.** "It runs" means you ran it and saw the
  output. "Should work" is not a result.
- **Secrets never go into code, documents, chat or memory.** They live in one `.env` file on the
  box. If a script needs a key, it reads that file.

---

## 1. Core ideas

These are the ideas the whole system is built on. If you keep only one section, keep this one.

### 1.1 Own data beats generic templates

Off-the-shelf tools (TrainingPeaks, intervals.icu, Garmin, WKO, readiness apps) all answer
questions *they* chose. None lets the athlete put a hypothesis in. An athlete with years of
power files and sleep data has a private dataset that is far more informative about *them* than
any population model. The engine exists to ask compound, conditional questions of that dataset
("after a four-day break, what happens to heart rate at 200 W on day one, two and three?") and to
turn the answers into rules the coach follows.

Consequence: every coaching rule in this system cites the athlete's own episodes. Generic
advice is explicitly banned from the coach's output.

### 1.2 One hub, one source of truth

- **intervals.icu is the hub.** Every ride (from any trainer app or head unit) and every
  night's physiology (from the watch, via the Intervals Companion iOS app) lands there. It has a
  good API, a calendar that pushes planned workouts to trainers and head units, and generous
  rate limits for one user. TrainingPeaks is kept only as a fallback and for its WKO substrate.
- **The FIT files are the source of truth.** Every original `.fit` is kept forever in an
  archive on the box, deduplicated by content fingerprint, mirrored cold to a NAS. Platforms
  come and go; the files do not.
- **Features are JSON tables, not a database.** A daily panel, a weekly panel, a health table,
  a per-workout table. Plain files, versioned by backup, readable by any script and by Claude
  directly. A database was planned and never needed.

### 1.3 Fixed references, honest measurement

- **FTP is a fixed reference number, not an outcome.** It is set by the athlete (275 W here)
  and never replaced by a platform estimate. intervals.icu's eFTP reads 244 for this athlete
  because he does no long all-out efforts; using it would silently rescale every zone and every
  TSS. Fitness is read from EF (normalised power ÷ average heart rate on steady rides), heart
  rate at fixed power on control workouts, decoupling, and nocturnal heart rate, never from FTP.
- **Compliance is measured honestly.** Two scores per workout: whole-workout (time and TSS
  versus plan) and main-set (seconds inside ±5% of target on 30-second smoothed power, work
  segments only). Erg rides score near 100%, outdoor rides honestly lower. A true 61% beats an
  inflated 73%.
- **Separate datasets stay separate.** Whole-ride numbers and main-set numbers are shown as
  two rows and never blended.

### 1.4 Control workouts are the instrument

Non-ladder days (the Wednesday Z2, the Friday Z1 spin, the Sunday long Z2) repeat the *same*
workout every week within a training block. At fixed erg power, heart rate, EF and decoupling
on those rides are directly comparable week over week. This is the cheapest and most reliable
fitness trend detector the athlete has, and no commercial platform provides it. The plan
generator must never vary a control workout inside a block.

### 1.5 Propose, never impose

The coach never silently changes a planned session. When the data warrants a change (poor
readiness on a quality day, illness, a reload after travel), it posts a proposal and the athlete
decides. **No response means the original plan holds.** The worst case of a missed message is
that the athlete rides the plan as written, never a plan that changed under him.

Operationally this became "propose, then deploy": every plan change is shown first (what
changes, which days, what it does to TSS), and pushed to the calendar only after a yes.

### 1.6 Research doctrine

For any pattern mining over the archive:

1. No pattern, no cue. A finding must hold in at least three independent blocks or seasons,
   with a minimum sample, sign-stable on a split-half test. Single cases are anecdotes.
2. Correlation is not dependency. Use lag structure for direction, partial correlations
   controlling for volume and fitness, and natural-experiment contrasts.
3. The implication bar: "A implies B" must survive its contrapositive. Enumerate every A
   without B explicitly; never average the exceptions away. Counterexamples go to the athlete
   with dates and context, and either refine the rule or kill it.
4. The athlete annotates context (trips, illness, life) before a finding becomes a rule. The
   data cannot see those.
5. Sweep wide, with multiple-testing discipline (permutation baseline, false-discovery
   control, report how many hypotheses were tested). **An honest "no pattern found" is a valid
   and preferred result over a biased finding.**
6. Use the trained-athlete era only (2020 onward here). Beginner years confound everything.

What this doctrine produced for this athlete (160 hypotheses, July 2026): weekly training
*composition* (sweet-spot versus threshold versus VO2) does not differentially move any
adaptation outcome. One acute signal survived: a hard day raises nocturnal heart rate the next
night and lowers it on night three (parasympathetic rebound, weak but robust). Practical
consequence: optimise execution, recovery and consistency rather than periodisation cleverness,
and read recovery on a 72-hour clock, not the next morning.

### 1.7 The LLM reads a doctrine, not a prompt

Claude is used in two narrow roles: a morning read before the day's session and a debrief after
each ride (plus an on-demand Slack coach). In each role it receives the day's numbers, the
baselines, the plan, and a **doctrine file** written in plain language from the athlete's own
episodes (what a high HRV after rest means for *him*, why heart rate at fixed power rises after
travel, when the one-minute HR drop matters). The doctrine is the product; the prompt is
plumbing. Every lesson learned goes into that file, so the coach gets better without code
changes.

### 1.8 Private, iPad-first, static

The athlete reads everything on an iPad. The site is static HTML, self-contained, dark-mode
aware, rebuilt every 15 minutes, served from a NAS under an unguessable path. Documents go to
a personal cloud drive, never a corporate one. Health data never enters any work system.

### 1.9 The box does the work, not the laptop

Every scheduled job runs on an always-on Linux box under systemd timers with failure
notifications. Nothing depends on a laptop being awake. The NAS is storage only.

---

## 2. Step one: history. Download everything, then analyse it

Before any coaching, assemble the archive. Everything later (baselines, doctrine, control
workouts, the plan's ramp rate) is derived from it.

### 2.1 Sources and how to get them

| Source | What it holds | How it was obtained | Notes |
|---|---|---|---|
| TrainingPeaks bulk export | 9 years of ride FIT files + a workout CSV with titles, RPE, feeling and athlete comments | Settings → export, year by year (two zips per year, ~275 MB total) | Files inside share generic names (`workout.fit.gz`) and collide on extraction. Extract per zip into dated folders, then hash. Both `.fit.gz` and `.FIT.gz` exist; glob case-insensitively. TP has no personal API. |
| intervals.icu | Every activity since the account started, with per-second streams; daily wellness | API, see section 3.6 | Activities uploaded via the API are stored but power summaries are not computed; streams are. Fine for our purposes, since we compute what we need. |
| Apple Health export | Heart rate (~3.5-minute samples at night), HRV (SDNN), sleep, resting HR, weight, VO2max | iPhone → Health → export (a 5.6 GB XML here) | One-off. The ongoing feed is a different mechanism (section 3.7). |
| Fitbit data export | Pre-Apple-Watch weight, sleep, heart rate | Fitbit account export | Historical weight was the valuable part. |
| MyFitnessPal export | Weight log 2010–2022, nutrition | Account export, CSV, day-first dates | Merged into the health table where Apple Health had gaps (276 days added). |
| Garmin Connect | Nothing unique here; Garmin is a sink in this setup | — | Used as the historical record for trainer-app rides, nothing is read back. |
| WKO5 files | Proprietary `.wko4` | — | Not parsed. Dead end; do not spend time on it. |

### 2.2 Consolidate: the FIT archive ("TheSource")

- One folder per year: `TheSource/fit/{YYYY}/`. 3,104 files, 6.1 GB, 2017 to today.
- Every incoming file (from the TP export, from the intervals.icu download lane, from the NAS
  inboxes that receive trainer and head-unit uploads) goes through `consolidate_fit_archive.py`,
  which fingerprints the session (start time, duration, distance, calories) and keeps the first
  copy. The same ride arriving via three paths is normal; the archive holds it once.
- An index file maps fingerprint → path, so later lanes are idempotent.
- The NAS holds a cold mirror. The NAS is RAID0 in this setup and is never the only copy.

### 2.3 Extract features

- `extract_workout_features.py` reads every FIT into one JSON line per workout: duration,
  distance, TSS, IF, kJ, average/max/normalised power, heart rates, the power sample count,
  time-in-band, EF and decoupling. This is the per-workout table (`workouts.jsonl`).
- `extract_health_series.py` turns the Apple Health XML into a daily health table
  (`health_daily.json`: weight, resting HR, SDNN, sleep seconds, VO2max, later respiration and
  wrist temperature from the ongoing feed).
- `calibrate_low30.py` computes, for every night in the archive, the **lowest 30-minute average
  sleeping heart rate**. This is the Garmin-style recovery number the athlete trusts most, and
  no platform exposes it. 3,097 nights here. The ongoing daily value comes from the health feed
  in section 3.7.
- `build_panel.py` assembles the daily panel (`panel_daily.json`: CTL, ATL, eFTP, low30, RHR,
  SDNN, sleep, VO2max, weight per date) and the weekly panel (`panel_weekly.json`: TSS, hours,
  kJ, rides, minutes per zone, EF, weight, RHR, low30, sleep per week). CTL and ATL are computed
  here from our own TSS, not imported.

### 2.4 Analyse: what to look for first

Run, in this order, because each result changes what comes next:

1. **Failure-mode reverse engineering.** Take the worst sessions (abandoned, bailed, "legs
   gone") and look 24–72 hours back: sleep, HRV, nocturnal HR, prior load, days since a break.
   This is the highest-leverage analysis and the one most athletes never do. For this athlete it
   found the 112% VO2 ceiling (≤112% of FTP completed 6 of 6 sessions, ≥113% on 3-minute reps
   failed 2 of 2) and the readiness gate (morning HRV under 40 or sleep under 6.5 h before a
   quality day predicted both spring DNFs).
2. **The canonical week.** Over the cleanest period (a winter indoor block is ideal), what did
   the athlete *actually* do consistently? Here: Monday walk, never a ride; at most three quality
   days, never adjacent; Wednesday and Sunday Z2 untouched for seven months; Friday an easy spin
   at IF ~0.57; three loaded weeks then one recovery week; recovery weeks keep the rhythm and
   weekend hours and drop watts. These became the generator's constraints.
3. **Baselines per condition.** EF on steady rides, indoor and outdoor separately (outdoor
   reads ~3–4% lower for the same power because of surges). Heart rate at 180–200 W. The
   one-minute HR drop after a hard effort (35–40 bpm when fresh here). Nocturnal HR and rMSSD
   28-day medians.
4. **The wide screen.** Only after the above, sweep composition × outcome × lag with proper
   multiple-testing control, expecting mostly nothing. Record the honest negatives; they stop
   future sessions from chasing the same ghosts.

### 2.5 Definition of done for step one

- The archive exists, is deduplicated, indexed, and has a cold mirror.
- The four feature files exist and cover the full history.
- A written analysis of failure modes, the canonical week, and baselines, with dates and
  counterexamples, approved by the athlete.
- A first version of the doctrine file (section 4.4) drafted from that analysis.

---

## 3. The backend

### 3.1 Hardware

| Role | What is used here | Minimum that would do |
|---|---|---|
| Engine | A small Ubuntu 24.04 box (Ryzen 5, 32 GB RAM, 1 TB NVMe), always on, on the home LAN and on Tailscale | Any always-on Linux machine with ~20 GB free. A Raspberry Pi 4 would cope; the heaviest job is a 30-second site rebuild. |
| Storage | Synology NAS: cold mirror of the FIT archive, Dropbox cloud-sync inboxes, a Web Station folder that serves the site | Any machine that can receive rsync and serve static files. Could be the engine itself. |
| Backup | restic nightly from the engine to the NAS and to a USB disk | Any off-box backup of the data directory. |
| Trainer PC | A Windows PC running the trainer apps (icTrainer, TrainingPeaks Virtual) with a shared folder | Only needed for the side lanes in section 3.9. |
| Devices | Wahoo Elemnt Ace head unit, Cycplus T7 smart bike, Assioma Duo pedals, Apple Watch, iPhone, iPad | Any power source, any watch that writes to Apple Health or Garmin, any device that syncs to intervals.icu. |

### 3.2 Software

- Python 3.12, system install, no framework, no virtualenv for the engine itself. The engine
  scripts import exactly one third-party package, `fitparse` (FIT decoding); everything else is
  the standard library (`urllib`, `json`, `statistics`, `subprocess`). The Garmin side lane has
  its own venv with `fit-file-faker`, `fit-tool`, `garth` and `watchdog`.
- `rclone` for the personal Google Drive (plans and documents up, health exports down).
- `smbclient` for pulling files from the trainer PC share.
- `rsync` to the NAS (Synology needs `--rsync-path=/usr/bin/rsync`).
- The Claude Code CLI installed on the box, authenticated once interactively; scripts call it
  non-interactively as `claude -p --model sonnet --dangerously-skip-permissions` with the prompt
  on stdin and a 180-second timeout (the flag only suppresses interactive prompts; the coach
  prompts use no tools). No Anthropic API key, no `anthropic` package: one subscription, two to
  four calls a day. The model alias is read from `WATCHMAN_MODEL` if set.
- systemd timers for everything scheduled. No cron, no laptop.
- Slack: one incoming webhook for the morning read and debriefs, one bot token (with
  `chat:write`, `groups:read`, `groups:history` for a private channel) for the conversational coach.

### 3.3 Directory layout on the box

```
/srv/scrapers/physiology-engine/
  scripts/            all scripts (section 3.5)
  config/             watchman_context.md (doctrine), t7.json, env_overrides.json
/srv/scrapers/fitfaker/      Garmin side lane (section 3.9), own venv
/srv/data/physiology/
  TheSource/fit/YYYY/ the FIT archive (source of truth)
  TheSource/fit_index.json, icu_pull_state.json
  sources/            raw mirrors: icu_downloads, incoming_dropbox, HealthFit,
                      health_auto_export, tpv_raw, MFP csv
  wellness/           one JSON per year of intervals.icu wellness, low30_history.json,
                      low30_calibration.json
  features/           panel_daily, panel_weekly, health_daily, workouts.jsonl,
                      card_cache, core_cache, fingerprint_cache, screening outputs
  plans/              week-YYYY-MM-DD.json, one per week of the season
  config/             season.json, ramp.json, sat_ladder.json
  outbox/             everything published: site/, reports, panel copies
  logs/               daily-*.log, debriefed.json, watchman_posted, coach_state.json
/srv/_env/.env        the only place secrets live
```

### 3.4 Secrets and environment

One file, `/srv/_env/.env`, `KEY=value` per line, read by a tiny loader at the top of each
script (strip quotes; `systemd` services need `Environment=HOME=/home/USER` for the Claude
CLI to find its login). Variable names used:

| Name | Purpose |
|---|---|
| `INTERVALS_API_KEY` | intervals.icu personal API key (Settings → Developer) |
| `INTERVALS_BASE_URL` | optional, defaults to `https://intervals.icu/api/v1` |
| `SLACK_WEBHOOK_CYCLING` | incoming webhook for the training channel |
| `SLACK_BOT_TOKEN_CYCLING`, `SLACK_CYCLING_CHANNEL_ID` | bot token and channel id for the conversational coach |
| `GARMIN_USERNAME`, `GARMIN_PASSWORD` | Garmin Connect login for the side lane |
| `TRAINER_PC_SMB_USER`, `TRAINER_PC_SMB_PASS` | share credentials on the trainer PC |
| `WATCHMAN_MODEL` | optional, Claude model alias for the coach lanes (default `sonnet`) |
| `HEALTH_MCP_TOKEN` | optional, Health Auto Export's local MCP server (probed, unused in production) |

Never put a value in a document, a chat message, a commit, or an AI assistant's memory. The
scripts in this repo contain none.

### 3.5 Scripts

See `engine/scripts/`. The table lists what runs in production; retired generators are not
shipped.

**Daily pipeline and archive**

| Script | Does | Reads | Writes |
|---|---|---|---|
| `physio_daily.sh` | The 04:10 chain, logged to `logs/daily-<date>.log`: rsync the NAS head-unit inbox → pull new activities from intervals.icu → consolidate into the archive → wellness snapshot → build site and rsync it to the NAS web folder → mirror the archive to the NAS cold copy → publish `outbox/` to the cloud drive → pull the plan documents folder down as a read mirror → prune logs older than 30 days | NAS inbox, intervals.icu, Drive | everything under `data/` |
| `pull_intervals_fits.py` | Downloads the original FIT of every activity not yet pulled, looking back 14 days before the newest pulled one; manual activities without a file are recorded as `no_file` | `GET /athlete/0/activities`, `GET /activity/{id}/file` | `sources/icu_downloads/<start>_<type>_<id>.fit`, `TheSource/icu_pull_state.json` |
| `consolidate_fit_archive.py --execute` | Fingerprint dedup (start time, elapsed time, distance, sport) of every inbox into the archive, first source wins in priority order (head unit, trainer app, intervals.icu download, HealthFit, TP history); canonical name `{YYYY-MM-DD_HHMMSS}_{sport}_{source}_{hash8}.fit`; dry run without `--execute` | `sources/*` | `TheSource/fit/{YYYY}/`, `fit_index.json` |
| `pull_wellness.py` | Snapshot of the whole wellness history (from 2010) into one JSON per year, every night | `GET /athlete/0/wellness?oldest=2010-01-01` | `wellness/YYYY.json`, `_pull_meta.json` |
| `extract_workout_features.py`, `extract_health_series.py`, `build_panel.py`, `calibrate_low30.py` | Section 2.3 | archive, health XML | `features/*`, `wellness/low30_*` |
| `health_export_low30.py` | Ongoing lowest-30 sleeping HR from the phone's daily health export (section 3.7) | Drive and Dropbox export files | `low30_history.json`, `health_daily.json` |

**Plan**

| Script | Does |
|---|---|
| `gen_season.py` | The season generator (section 5). Builders for each day type, ladders by week number, writes `plans/week-*.json` with `--write`, prints a formulation table and a CTL simulation otherwise. |
| `push_week.py <plan.json> [--all]` | Converts each structured day to a `.zwo` and POSTs it as a WORKOUT event to intervals.icu. Idempotent: deletes that date's unpaired WORKOUT events first. Past days skipped unless `--all`. |
| `push_workout.py <plan.json> <day-idx> <date>` | Same for a single day (used for swaps). |
| `push_upcoming.sh` | Friday 07:00: push next Monday's whole week. |

**Site**

| Script | Does |
|---|---|
| `make_site.py` | Builds the whole static site: overview, one page per week (cards per day with plan / actual / main-set rows, form hero, compliance footers, wellness strip above today), the ATP page, the season page, and calls `analytics_page.py`. Pulls activities, wellness and streams live from intervals.icu, caches per-activity analysis in `card_cache.json`. Section 6.2 explains the matching. |
| `analytics_page.py` | Trend charts (rMSSD, lowest-30 sleeping HR, weight versus target, main-set EF and decoupling on steady rides, indoor versus outdoor) for 30/90/180/365/730-day windows, inline SVG. |
| `core_metrics.py` | Per-ride EF and decoupling for the charts: uses the card's main-set numbers when the ride was plan-matched, else trims the first 12 and last 6 minutes of the stream. |
| `refresh_site.sh` | `make_site.py` then rsync to the NAS web folder. This is the deploy; running `make_site.py` alone changes nothing visible. |

**Coach**

| Script | Does |
|---|---|
| `physio_ctx.py` | Shared context module: `readings()` (today's wellness versus 28-day medians, CTL/ATL/TSB), `rides()`, `history_block()` (EF baselines, CTL now/4 weeks/10 weeks, week plan versus actual, last 12 rides with RPE and feel), `formula(day)` (renders the plan's real segments as text so the LLM cannot invent a structure), `is_indoor()` (the power fingerprint rule), `is_test()`, `low30()`, `claude()`, `slack_post()`. |
| `watchman.py` | The morning read (section 6.3). Timer at 11:00 with a retry at 11:30. |
| `ride_debrief.py` | Every 15 minutes: any newly cached ride that has not been debriefed gets one post (section 6.4). State in `logs/debriefed.json`. |
| `cycling_coach.py` | A 30-second poller answering the athlete's messages in the training channel, in thread, with the same context. |
| `dual_check.py`, `dual_fit.py` | When a trainer-app file carries both trainer and pedal power, compare them and report the ratio (section 7.6). |
| `screen_daily.py`, `screen_weekly.py` | The research sweeps from section 2.4, kept for re-runs. |

### 3.6 intervals.icu API, the facts that cost time to learn

- Base `https://intervals.icu/api/v1`. HTTP Basic with username the literal string `API_KEY`
  and password the key. **Always send a User-Agent header**; the default Python one is blocked
  by Cloudflare (error 1010).
- Use athlete id `0` for your own data: `/athlete/0/activities`, `/athlete/0/wellness`,
  `/athlete/0/events`. The real id returns 403 on the activities endpoint.
- Wellness needs a date range or it returns 500.
- Per-second streams: `GET /activity/{id}/streams?types=watts,heartrate,cadence,latlng`.
  Laps: `GET /activity/{id}/intervals` → `icu_intervals` with `start_index`/`end_index`.
- Planned workouts: `POST /athlete/0/events` with `category: WORKOUT`, `start_date_local`,
  `type: Ride`, `name`, `filename: workout.zwo`, `file_contents: <zwo xml>`. The event appears
  in the Companion app and syncs to the head unit and to trainer apps that read the calendar.
- Uploading a ride: `POST /athlete/0/activities?name=...` multipart `file`. It pairs with the
  planned event automatically.
- `PUT /activity/{id}` often answers 500 while the change persisted. Verify with a GET.
- The "today" CTL/ATL in wellness **includes today's planned workout**. Read form from
  yesterday's record, or after the day's event is gone.
- Activities deleted in the UI simply return 404; nothing tells you who deleted them.
- The athlete's RPE (`icu_rpe`, 1–10) and feel (`feel`, 1 strong … 5 weak) are on the
  activity; readiness and comments are on wellness. All of them feed the coach.
- Rate limits are generous: one request a second for thousands of requests was never throttled.

### 3.7 The physiology feed (watch → engine)

Two lanes, both needed, because phone automations are fragile:

1. **Intervals Companion (iOS)** syncs eleven daily metrics from Apple Health to intervals.icu:
   rMSSD and SDNN, resting HR, sleep and sleep score, readiness, SpO2, respiration, steps, average
   sleeping HR, weight on scale days. This is the main lane and the one the morning read uses.
   Overnight data is in intervals.icu by about 11:00 local, which is why the morning read runs
   then.
2. **Health Auto Export (iOS) → Dropbox → NAS cloud sync → engine** for the raw per-minute
   night heart rate, from which the engine computes the lowest-30-minute sleeping HR (the number
   the Companion does not upload). Triggered by an iOS Shortcut automation that fires when the
   phone is unlocked in the morning (time-of-day triggers export empty files on a locked phone).
   `health_export_low30.py` merges the two export flavours by minute, ignores empty files, and
   appends to `low30_history.json`. When no export arrived the read shows an estimate marked ≈.

### 3.8 Scheduling (systemd timers on the box)

| Timer / unit | When | Runs |
|---|---|---|
| `physio-daily.timer` | 04:10 | `physio_daily.sh` |
| `physio-refresh.timer` | every 15 min | `refresh_site.sh` |
| `physio-pushweek.timer` | Friday 07:00 | `push_upcoming.sh` |
| `physio-watchman.timer`, `physio-watchman-retry.timer` | 11:00, 11:30 | `health_export_low30.py` as ExecStartPre, then `watchman.py` (the retry exits at once unless the first run left a marker) |
| `physio-debrief.timer` | every 15 min at :05/:20/:35/:50 (offset so the site refresh has filled the card cache) | `dual_check.py` as ExecStartPre, then `ride_debrief.py` |
| `cycling-coach.service` | always | `cycling_coach.py` |
| `fitfaker.service`, `fitfaker-sync.timer` (2 min), `ictrainer-pull.service`, `tpv-pull.service` | always / 2 min | Section 3.9 |

Every unit has an `OnFailure=` drop-in that posts the unit name to an ops channel, a start
limit (five restarts per ten minutes, then it stays failed and reported), and services that
process files quarantine a file that throws instead of dying on it. Unit files are in
`engine/systemd/`.

### 3.9 Side lane: trainer-app rides into Garmin Connect

Trainer apps upload to intervals.icu and TrainingPeaks but not all of them to Garmin, and the
athlete wants Garmin as the long-term personal record. The lane:

- Head-unit rides arrive via Dropbox cloud sync on the NAS; a 2-minute timer rsyncs them to an
  inbox on the box; `fit-file-faker` (open source, with a small local patch) rewrites the
  file's device identity to a Garmin Edge and uploads with `garth`.
- icTrainer writes a FIT that `fit_tool` cannot re-encode cleanly, so `ict_fix.py` patches the
  identity bytes in place (file id and device info → Garmin / Edge 840, CRCs recomputed) and
  `garmin_upload.py` sends it. `pull_ictrainer.sh` polls the trainer PC's share and keeps a
  `.ictrainer_seen` list so nothing uploads twice; `_garmin.fit` twins are skipped.
- `ictt_tmp_to_fit.py` rebuilds a full 1 Hz FIT (power, cadence, HR, laps, NP/IF/TSS) from
  icTrainer's live `.ictt.tmp` log when the app fails to save a ride. Runbook in section 7.4.

Garmin does not fan workouts back out to other platforms, so this lane is purely the record.

### 3.10 Costs

- Hardware already owned. The box draws about 15 W.
- intervals.icu: free tier is enough; the athlete pays the small supporter fee.
- Claude: one Claude subscription, two to four CLI calls a day. No API spend.
- Slack free workspace.

### 3.11 Definition of done for the backend

- The daily chain runs from a timer and the log shows every stage.
- The site rebuilds every 15 minutes and is reachable on the iPad.
- A failed unit produces a message somewhere a human reads.
- `.env` is the only file with a secret in it, and it is not in any backup that leaves the house unencrypted.

---

## 4. Know your athlete

The engine is only as good as this section. It is a *written* description, approved by the
athlete, and it lives in three places: this document (the long form), the doctrine file the
LLM reads (`engine/config/watchman_context.md`, the operational form), and the generator's
constants. Appendix A is the questionnaire that produces it.

### 4.1 Goals

Stated by the athlete, with a date and a measurable shape. For Egor in autumn 2026:

- The event: a single ~9.5-hour Teide ride on 27 December 2026, IF about 0.64, a 3-hour climb
  then rollers. No races, nothing forced.
- The precedent, from his own history: both previous Teide rides (April 2025, 10.5 h, 462 TSS,
  CTL 84; June 2026, 9.5 h, 368 TSS, CTL 82) were ridden at the CTL peak, inside the build,
  with no long taper. So the target is a fitness number he has reached before: CTL ~76 at the
  peak on 7 December, entering the ride around 71 after the travel week, with three easy
  re-entry days after the flight.
- A body-weight target alongside: 80 kg by 15 December (from 91.6 in mid-September).

### 4.2 Today's fitness (22 October 2026, from the engine)

| Measure | Value | Source |
|---|---|---|
| CTL / ATL / TSB | 55 / 72 / −15 | intervals.icu, end of yesterday |
| FTP (fixed) | 275 W | athlete |
| HRmax | ~185 | athlete |
| rMSSD (today / 28-day median) | 26 / 26.5 | Companion |
| RHR (today / median) | 54 / 59 | Companion |
| Lowest-30 sleeping HR (today / median) | 55 / 56 | health export lane |
| Z2 EF baseline, last 150 days | outdoor 1.41 (n=26), indoor 1.46 (n=14) | engine |
| One-minute HR drop after a hard effort, fresh | 35–40 bpm | engine |
| CTL 4 weeks ago / 10 weeks ago | 45 / 53 | intervals.icu |

The last fortnight reads as a clean build: sweet-spot sessions at EF 1.53–1.56 with feel
"strong", Z2 control rides at EF 1.44–1.47, RPE 4–7.

### 4.3 Limitations and personal rules (from data, dated)

- **Warm-up sensitive.** Under-warmed sessions are poor; he feels best at the 60-minute mark.
  The classic warm-ups (section 5.3) are never trimmed and key blocks sit at or after one hour.
- **VO2 ceiling 112% of FTP.** Above it, 3-minute reps fail. Progress one axis at a time
  (reps, then duration, then power). Maximum two suprathreshold sessions per rolling 7 days.
  No VO2max tests or ramp tests at all: they cost freshness and change nothing he does.
- **Readiness gate.** Morning rMSSD under 40 or sleep under 6.5 h before a quality day: swap it
  to Z2. (Rule currently kept as a proposal trigger, not an automatic change.)
- **Reload shock.** After four or more days off (travel), heart rate at fixed power rises and
  EF drops for two to three days (plasma volume), rMSSD rebounds high then collapses if loaded,
  and the first high-tension sessions land in a DOMS window. This looked like overtraining in
  September 2026 and was not. Rule: after ≥4 days off, three days Z2, first hard session on day
  four or later. Transitions, not steady ramps, are where he breaks. Age 59 makes transitions
  bite harder.
- **Illness.** Sleeping HR up by 4 or more for two nights, or symptoms: a full Z2 week, no
  debate, regardless of phase.
- **TSB bands, tighter than TrainingPeaks:** above +5 fresh (blue), −5 to +5 neutral, −15 to −5
  productive (green), −25 to −15 caution (orange), below −25 trashed (red). He rides fine at −15;
  deeper than −20 for two days means ease off.
- **Clean reps beat crammed reps.** If a rep degrades, lengthen the valley or drop 1%; never
  push a dirty interval. For reps over 10 minutes at sweet-spot, valleys are 5 minutes, not 3
  (October 2026: "3' won't help to recover fully, either 5' or run all the way through").
- **Cadence ~70 rpm.** He is a masher. Never prescribe 85–90.
- **Long indoor rides are misery.** The indoor long ride is a 2:15–3:00 undulating Z2 "wave",
  three hours only occasionally.
- **Recovery weeks** (every fourth): rhythm unchanged, weekend hours kept, watts down, nothing
  above IF 0.72, total 75–85% of a loaded week.
- **RPE and feel**, entered after each ride, are read against the numbers: RPE ≥7 on an easy
  ride, or feel 4–5 on a day the power was fine, is the earliest fatigue signal and beats HR drift.

### 4.4 The doctrine file

`engine/config/watchman_context.md` is the operational form of this section: ~60 lines the LLM
reads before every morning read and every debrief. It states who the athlete is, what each
number means *for him* (with the September 2026 episode as the worked example), the alarm
thresholds the script computes, how to read an outdoor ride versus an indoor one, and what not
to comment on (HR drop on easy rides, test files, missing RPE). When a lesson is learned, this
file changes the same day.

### 4.5 Definition of done

The athlete has read sections 4.1–4.3 and the doctrine file and says "that is me". Every rule
carries a date and an episode. Anything the athlete disputes is removed, not softened.

---

## 5. The plan

### 5.1 Season definition (`config/season.json`)

Named blocks with a first Monday, a length in weeks, a one-line focus, and an `off` flag for
trips. Autumn 2026: Pre-USA (hold) → USA (off, CTL decays to ~45, priced in) → Base 1, 2, 3
(sweet-spot ladder) → Specificity → Taper → Teide. The site's week pages are addressed by block
and week number.

### 5.2 Ramp table (`config/ramp.json`)

One row per week: Monday, block, label, target TSS, recovery flag, planned CTL and TSB, ramp
rate. Rebuilt whenever the plan changes. Start CTL 43 on 21 September, target 76, three loaded
weeks then one recovery week, +2 to +2.5 CTL per week, which is what his 2025 build did cleanly.

### 5.3 The generator (`gen_season.py`)

A plan week is a list of seven day objects. A day has a name (its role: "Long SST", "The Z2
Wave"), a type (SST, Tempo, THR, Z2, Z1, Walk, Rest), a `summary` (one line), `details`
(the exact structure in words, shown on the card), and `segments`: a list of
`["ss", seconds, %FTP, role]` or `["ramp", seconds, from%, to%, role]`, where role is one of
`wu`, `work`, `rec`, `filler`, `cd`. Only `work` segments feed main-set compliance. TSS and IF
are computed from the segments, never hand-written.

Fixed building blocks (locked, from years of use):

- **Core warm-up (~22'):** 5' @40% → ramp 5' 40→80% → 1' @40 → ramp 3' 70→90% → 1' @40 →
  fast legs 2×(1' @90 + 1' @40) + 1' @90 → one 4' @40 valley. (Sweet-spot and tempo days.)
- **Threshold warm-up:** core + 3' @100% opener + 4' @40.
- **Z2 days:** 5' @40 + 3' ramp to target; cool-down 5' ramp to 30%. Ramps stay ramps in the
  `.zwo`; the Wahoo renders a ramp as a flat block at its mean and the athlete accepts that.
- **Tuesday sweet-spot ladder:** 3×12' → 3×15' at 88→92%, 5' valleys and 2' rec for reps over
  10', Z2 tail trimmed so the ride length stays the same. Capped at 3×15'.
- **Thursday:** tempo 2×20' → 3×20' at 80% (5' valleys) through week 6, then threshold
  3×8' → 3×10' at 100–102%.
- **Saturday consolidation ladder:** 9×6' @86% → 6×11' @89% → 4×18' @91% → 3×26' → 2×40' →
  2×44' @92% → 1×90' straight @92% at the peak. Valleys 3.5' → 10' with rep length.
- **Sunday, "The Z2 Wave":** n×14' cycling 65/70/75/70%, 2:15 → 3:30. The durability ride.
- **Wednesday control Z2:** 78', steps 65-70-75-70-75% (load in gently). **Friday:** Z1 spin at
  55%. **Monday:** walk, ~9 TSS as intervals.icu scores it.
- **Recovery weeks:** three days of 90' low Z2 at 62–65%, Saturday and Sunday long Z2 at 66%.
- **Travel weeks** are written as rest days with notes; re-entry days are Z2 only.

The generator prints a formulation table (every Tuesday, Thursday, Saturday, Sunday for all 14
weeks) and a CTL simulation, so a change can be reviewed before `--write`. It writes one JSON
per week. Past weeks are never regenerated; a plan file is history once its week has started.

### 5.4 Getting it to the trainer

Friday 07:00 the whole following week is pushed to intervals.icu as `.zwo` workouts. The
Companion app, the head unit and the trainer apps pick them up from the calendar. The push is
idempotent (replace, not duplicate) and skips past days, so a workout the athlete edited by
hand in the calendar is not overwritten once its day has passed. Edits made in the calendar do
**not** flow back into the plan files; when the athlete changes a workout the engine must be
told, or the card will compare against the old structure.

### 5.5 Changing the plan: propose, then deploy

Any change to a future workout follows the same steps, and this is the single most important
operating rule:

1. Make the change in the generator (so the rule persists), regenerate into a temporary folder,
   diff against the live plan files day by day.
2. Show the athlete exactly which days change and the TSS and duration deltas. Take only the
   days that were asked for; a regenerated file can carry unrelated drift.
3. On a yes: copy the changed weeks (never past weeks), push this week and next to the
   calendar, rebuild the site.
4. Back up every file touched with a dated suffix.

### 5.6 Definition of done

A season file, a ramp table, 14 week files, a formulation printout the athlete approved, the
next week visible in the calendar and on the trainer app.

---

## 6. Monitoring, feedback, everyday analysis

### 6.1 The daily cycle

| Time | What happens | Who sees it |
|---|---|---|
| 04:10 | Daily chain: new rides into the archive, wellness snapshot, features, site rebuild, Drive publish | — |
| ~10:30 | Phone exports overnight health data when unlocked; Companion syncs to intervals.icu | — |
| 11:00 | Morning read: readings vs medians, yesterday's ride, today's session; Claude writes the read; posted to Slack | athlete |
| every 15 min | Site refresh; debrief of any new ride; dual-power check if a trainer-app file has two channels | athlete |
| after a ride | Athlete enters RPE and feel in the Companion app | coach |
| any time | Athlete asks the coach in the Slack channel; it answers in thread with full context | athlete |
| Friday 07:00 | Next week pushed to the calendar | athlete, trainer app |

### 6.2 The site

Static, one page per week, cards per day. Each card:

- **Header:** date, name, summary, indoor/outdoor pill, and the **form hero** (CTL/ATL/TSB
  banded by the athlete's TSB bands; actual for past days, projected for future days).
- **Body:** the workout profile drawn from the segments, zone-coloured, next to a three-row grid
  (Plan, Actual whole ride, Main set) with duration, TSS, IF, NP, kJ, cadence, HR, EF, VI,
  Pw:HR drift.
- **Footer:** compliance pills (TSS delta, time delta, main-set in-target %, reps missed) plus
  the athlete's RPE and feel, coloured by the doctrine (RPE ≥7 on an easy ride turns orange).
- Above today's card, a wellness strip (readiness, sleep, rMSSD, lowest-30 sleeping HR, weight).
- Rest days, empty days, unplanned rides, walks, extra rides on the same day all have their own
  card states; rides are never merged.

**Main-set matching.** The plan's segment durations form a fingerprint. The engine aligns the
plan's segments to the ride's laps with an exact dynamic-programming alignment (anchors where
durations match within 10%, "blob" laps that contain several plan segments placed by offset,
a lap may be skipped at no cost). This survives glitch laps from a pause, an aborted first
attempt, or a ride stitched from two apps. Without usable laps it slides the expected power
profile over the actual power and takes the best fit. Each work window is then checked (±10%
mean power = rep executed) and scored (seconds inside ±5% of target on 30-second smoothed
power). Outdoor rides are judged by NP against the band, not by in-target percent.

**Analytics page:** rMSSD, lowest-30 sleeping HR, weight versus the target line, main-set EF
and decoupling on steady Z2 rides (indoor and outdoor as separate series, five-ride medians),
30 to 730-day windows.

**ATP page:** the ramp table with planned versus actual CTL, self-updating from the plan files
and today's real CTL.

### 6.3 The morning read

`watchman.py` collects today's readings and 28-day medians, computes the rule flags (rMSSD
under 70% of median with RHR up 4 → two days red; sleep under 6 h; steady-ride EF under 90% of
baseline; first ride after ≥4 days off; sleeping HR up 4 for two nights), formats yesterday's
ride, renders today's planned session from its real segments, and hands all of it with the
doctrine to Claude. The post is short: a status icon, *Recovery / Load / Yesterday* lines in
integers, *Today* with the session, then *Body / Session / Watch* in two or three sentences.
If the overnight data has not arrived it stays silent and retries at 11:30; still nothing →
"no overnight data synced, check watch sync". One post per day, guaranteed by a marker file.

### 6.4 The ride debrief

Within 15 minutes of a ride reaching the archive, one post: a header line (name, indoor or
outdoor, duration, NP as % of FTP, TSS versus plan) and a Claude narrative in fixed sections
(*In short / Went well / Not ideal, watch / Trend / Verdict / Next*) with at most six numbers.
The prompt carries the card's compliance numbers, main-set EF and drift, the history block
(baselines, CTL trajectory, the week so far, the last 12 rides), RPE and feel, and the
doctrine's "how to read a ride" rules. Test files and calibration rides are never debriefed.

### 6.5 Everyday analyses the athlete actually uses

- Control-workout trend: HR and EF on the same Wednesday and Sunday workouts, week over week.
- Main-set EF and drift on quality days: the durability signal.
- Lowest-30 sleeping HR and rMSSD against their 28-day medians: recovery.
- Weight, 7-day mean, against the target line.
- The 72-hour clock after hard days (section 1.6).

What was tried and dropped: a daily push report (became a ritual nobody acted on), readiness
scores, VO2max tracking, imported platform CTL.

### 6.6 Definition of done

A morning read and a debrief have each been posted from the timer, not by hand, and the
athlete has said they are useful. The site shows a completed workout with honest compliance.

---

## 7. Runbooks

### 7.1 Daily, for the athlete

Ride. Save the ride in the app. Enter RPE and feel in the Companion app. Read the debrief.
Read the morning read before the next session. That is all.

### 7.2 Weekly, for the engine operator (the athlete's Claude)

- Friday: confirm the push happened (events for next week exist in intervals.icu).
- Sunday: look at the week page; if the ramp drifted, say so and propose, do not change.
- Any time the athlete states a rule ("valleys are 5' now"): change the generator, regenerate,
  diff, show, deploy on a yes, record the rule in the doctrine and in section 4 with the date.

### 7.3 A workout in the calendar but not on the site

Probably deleted and re-created, or deleted by a duplicate cleanup. Check the stored FIT in the
archive (the daily chain keeps it even when the platform copy is gone), re-upload it to
intervals.icu, mark the id as already debriefed so it does not get a second debrief.

### 7.4 The trainer app failed to save the ride

icTrainer keeps a live text log (`<rider>.ictt.tmp`) during the ride. Copy it from the trainer
PC, run `ictt_tmp_to_fit.py <tmp> <out.fit>`, check NP/duration/laps against what the athlete
remembers, upload the FIT to intervals.icu (pairs with the plan), upload to Garmin with
`garmin_upload.py`, and drop a copy on the drive for TrainingPeaks. Verified in October 2026
against a saved pair: 94% one-second power match.

### 7.5 After travel or ≥4 days off

Three Z2 days before the first hard session, whatever the plan says. Expect HR up and EF down
on days one and two; do not call it fitness loss and do not test FTP. The morning read will say
"re-entry window".

### 7.6 After a trainer firmware update

Ride one check session with the pedals paired as a second power source (ERG steps at 150, 200,
250 W). `dual_check.py` posts the pedal ÷ trainer ratio and a suggested correction. Compare
pedals only with the trainer's recorded power, never with the ERG set point. The Cycplus T7
was accurate within 1% at its default 97% transmission coefficient; a "3% drift" in September
2026 turned out to be a set-point artifact.

### 7.7 A unit failed

The OnFailure hook posts the unit name. `journalctl -u <unit>`; fix; `systemctl restart`. A
file that crashes a processing service is in its `quarantine/` folder. The watchman principle
applies to every unattended job: restart first, alert when restarts fail.

### 7.8 Adding a data source

Land raw files in `sources/<name>/`, write one extractor that fills only *missing* keys in the
feature tables, rebuild the panel, add a line to this document and to the archive mirror.

### 7.9 Changing the doctrine

Edit `watchman_context.md`, date the line, give the episode. Run `watchman.py --dry` to see
the read change. No code deploy needed.

---

## 8. Gotchas and lessons, dated

- Platform CTL is not ground truth; compute it from your own TSS (May 2026).
- intervals.icu's today CTL/ATL includes today's planned workout (October 2026).
- Apple Health HRV is SDNN; the Companion delivers sleeping rMSSD. Trend only, never compare
  absolutes across devices (May 2026).
- TrainingPeaks export files collide on generic names; extract per zip and hash (May 2026).
- Garmin does not fan out workouts to other platforms (May 2026).
- Phone time-of-day automations export empty files when the phone is locked; trigger on app
  open instead (September 2026).
- A trainer app with both trainer and pedal power paired records the pedals as the primary
  channel; the trainer is only in a developer field (September 2026).
- Multiple rides on one day are never merged; one is the workout, the others are extra cards
  (July 2026).
- Indoor versus outdoor is decided by the power fingerprint (jitter and coasting), not by GPS
  or device name, because pedals can be on the trainer (September 2026).
- Running the site builder alone deploys nothing; the refresh script does the rsync (July 2026).
- A greedy lap-to-plan matcher collapses on glitch laps; use an alignment that may skip laps
  (October 2026).
- Calendar edits do not flow back to the plan files; tell the engine (October 2026).
- The box is for work; personal archives live on the NAS and the cloud drive (October 2026).
- `.env` values may be quoted; strip quotes. systemd services need `HOME` set for the Claude
  CLI (September 2026).

### 8.1 Known weaknesses of the running system (inventory of 22 October 2026)

Listed so the next builder does better, not worse.

- The engine code on the box is not under version control; history lives as dated `.bak`
  copies. Fix: `git init` on day one.
- The nightly chain publishes `outbox/` to the cloud drive at about 04:14 while the 15-minute
  site refresh rewrites `outbox/site/` at 04:15; the drive sync occasionally fails with
  "source file is being updated". Fix: run the refresh timer only between 05:00 and 23:59, or
  publish from a snapshot copy.
- The consolidator reports two unparseable source files every night and nobody is told. Fix:
  move failures to a `quarantine/` folder once and report them.
- Hosts and paths are literals across six files although `.env` has `NAS_HOST`-style names.
  The shipped copy uses placeholders; a rebuild should read them from `.env`.
- The Claude model is an unpinned alias; a model change could change the coach's tone
  overnight. Pin it when stability matters more than freshness.
- The Slack coach daemon has no health check beyond systemd's restart; it crashed on a DNS
  blip and recovered, but a silent hang would go unnoticed. A heartbeat file plus a check in
  the morning read would close that.
- Several research scripts and two older generators are kept but have no caller; they are not
  shipped here, and are listed in section 3.5 as history only.

---

## 9. Placeholders in the shipped code

| Placeholder | Replace with |
|---|---|
| `NAS_HOST`, `$NAS_SSH` | your NAS address and `user@host` for rsync and ssh |
| `/volume1/...` | your NAS share paths |
| `SITE_FOLDER`, `YOUR-NAS-HOSTNAME` | the web folder and hostname that serve the site |
| `TRAINER_PC_HOST`, `TRAINER_PC` | the Windows trainer PC's address and share name |
| `YOUR_DRIVE_FOLDER_ID`, `YOUR_DRIVE_BACKUP_FOLDER_ID` | Google Drive folder ids for the health export lane |
| `gdrive-personal:` | your rclone remote name |
| `/home/USER`, `USER@ENGINE_HOST` | your user and box |
| `watchman_context.md` | your athlete, your episodes |
| `FTP = 275`, zone palette, TSB bands | your numbers |

---

## 10. Glossary

- **ATL / CTL / TSB** — acute (7-day) and chronic (42-day) exponentially weighted training load, and their difference, the "form". Computed from TSS.
- **TSS / IF / NP** — training stress score, intensity factor (NP ÷ FTP), normalised power (30-second rolling fourth-power mean).
- **EF** — efficiency factor, NP ÷ average HR on a steady ride. The fitness signal used here.
- **Decoupling (Pw:HR drift)** — power-to-HR ratio of the first half of a block versus the second; ≤3% clean, 3–5% meh, >5% fatigue, heat or dehydration.
- **Main set (MS)** — the work segments of a workout; everything else is warm-up, recovery, filler, cool-down.
- **Control workout** — the same fixed-power workout repeated weekly so HR and EF are comparable.
- **Low30** — the lowest 30-minute average heart rate of the night, the recovery benchmark.
- **rMSSD / SDNN** — two HRV measures; rMSSD (sleeping, from the Companion) is the one the coach reads.
- **Reload shock** — the HR-up, EF-down, HRV-collapse signature in the first days back after a break. Not fitness loss.
- **Readiness gate** — the rule that swaps a quality day to Z2 on poor morning numbers.
- **The Z2 Wave** — the Sunday long ride, 14-minute steps cycling 65/70/75/70% of FTP.
- **Sweet-spot (SST)** — 88–92% of FTP. **Tempo** 80%. **Threshold** 100–102%. **Z2** 65–75%. **Z1** ~55%.

---

## Appendix A. Onboarding questions Claude asks before building

Ask these in one message, wait for the answers, then build.

**About you**
1. Age, sport, years training with power, current FTP (and whether you want it fixed as the reference).
2. HRmax, resting HR range, and whether you record HRV (which app, rMSSD or SDNN).
3. Your target event or goal, with a date and what "done" looks like (duration, intensity, a fitness number you have reached before).
4. Known limitations: injuries, illness patterns, what kind of session has failed for you and when, how you respond to travel and breaks.
5. Preferred cadence, warm-up habits, indoor tolerance, days that are fixed by life (work, family).

**Your history**
6. Where your past rides live (TrainingPeaks, Strava, Garmin, intervals.icu, files) and how far back.
7. Where your physiology lives (Apple Health, Garmin, Oura, Whoop, Fitbit) and whether you can export it.
8. Any weight or nutrition logs.

**Your setup**
9. Which trainer apps and head unit you ride with, and which platforms they upload to.
10. Do you have an always-on Linux machine, a NAS, or neither? Which cloud drive do you use personally?
11. Where should the coach talk to you (Slack, Telegram, email) and in which hours must it stay quiet?
12. Do you have a Claude subscription (for the CLI on the box) or an API key?

**Your preferences**
13. How terse do you want the coach? What should it never comment on?
14. Which days are your control workouts going to be?
15. Do you want the readiness gate automatic or proposal-only? (Recommended: proposal-only.)

**Consent**
16. Confirm that nothing about your health leaves your own machines and accounts, and name the one file that will hold secrets.

## Appendix B. Build order checklist

1. `.env` on the box; intervals.icu key works (`GET /athlete/0/wellness` for yesterday).
2. Archive: all history files in, consolidated, indexed, mirrored.
3. Features: four tables built; spot-check five dates against the platform.
4. Analysis written and approved; doctrine v1 written.
5. Season and ramp files; generator prints the formulation table; athlete approves.
6. Week files written; first push to the calendar; workout visible on the trainer.
7. Site builds and deploys from the timer; today's card shows the plan.
8. Morning read posts from the timer with real data.
9. First ride debriefed from the timer.
10. Failure notifications tested with a deliberately broken unit.
