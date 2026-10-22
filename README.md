# Physiology Engine — a personal AI training backend for one endurance athlete

This repository documents, end to end, a working system that one ultra-endurance cyclist
(Egor, 59, FTP 275 W) built with Claude between May and October 2026 and trains on every day.
It is published so that another athlete can hand it to their own Claude and rebuild it for
themselves.

**Start here:** [`ARCHITECTURE-AND-SOP.md`](ARCHITECTURE-AND-SOP.md). It is written for an AI
assistant as much as for a human: give the file to Claude, tell it "build this for me", and it
will ask you the questions in the onboarding section and then construct the system step by step.

What the system does, in one paragraph: every ride and every night of sleep lands in
intervals.icu; a small Linux box pulls the data, keeps a nine-year archive of FIT files,
generates the training plan from a season definition, pushes each week's workouts to the
calendar (which flows to the trainer app or head unit), rebuilds a private static website with
plan-versus-actual cards and trend charts, and twice a day lets Claude read the numbers against
a doctrine written from the athlete's own history: a morning read before the session and a
debrief after each ride, both delivered to Slack. The athlete stays in control: nothing on the
plan changes without an explicit yes.

## Repository layout

| Path | What it is |
|---|---|
| `ARCHITECTURE-AND-SOP.md` | The document. Ideas, history ingest, backend, the athlete, the plan, the feedback loop, runbooks, gotchas, glossary. |
| `engine/scripts/` | The production Python and shell scripts, sanitised (host names, folder ids and IPs replaced by placeholders, see the SOP's placeholder table). Secrets were never in code; they live in a `.env` file the scripts read. |
| `engine/config/` | The coach doctrine (`watchman_context.md`) and small config files. |
| `engine/fitfaker/` | The side lane that gets trainer-app FIT files into Garmin Connect, plus the recovery tool for a ride the trainer app failed to save. |
| `engine/systemd/` | Unit and timer files for the scheduled jobs. |
| `engine/examples/` | Shapes of the data files (a week plan, a season definition, a ramp table, a card-cache entry) so the structure is unambiguous. |

## Honesty notes

- The code is the real code, lifted from the production box in October 2026 and lightly
  sanitised. It is written for one athlete and one home network. Expect to adapt paths, hosts
  and the doctrine. It is not a packaged product and has no test suite.
- Numbers in the athlete sections are Egor's real numbers, published with his consent. They are
  an example of *how* to describe an athlete, not targets for anyone else.
- Nothing here is medical advice.

## License

MIT for the code and CC BY 4.0 for the document. Attribution: Egor Pravilov, built with Claude.
