#!/usr/bin/env python3
"""Consolidate all .fit files from every source into the canonical archive (MP100 edition).

Migrated from the NAS 2026-07-11. Sources are local mirrors of the NAS inboxes,
refreshed by pull_sources.sh before this runs.

Sources (in priority order — first wins on dedup collision):
  1. wahoo   → /srv/data/physiology/sources/incoming_dropbox/    (Wahoo → Dropbox → NAS → mirror)
  2. tpv     → /srv/data/physiology/sources/incoming_tpvirtual/  (TPV Windows SMB → NAS → mirror)
  3. hfit    → /srv/data/physiology/sources/HealthFit/           (HealthFit → GD → NAS → mirror)
  4. tp-hist → /srv/data/physiology/sources/tp-extracted/        (static historical; fully ingested,
                                                                  dir intentionally NOT mirrored — stays on NAS)

Target: /srv/data/physiology/TheSource/fit/{YYYY}/
Index:  /srv/data/physiology/TheSource/fit_index.json

Canonical filename: {YYYY-MM-DD_HHMMSS}_{sport}_{source}_{8-char-hash}.fit (raw, ungzipped)
Dedup fingerprint: (start_time_utc, total_elapsed_time, total_distance, sport)
Resumable: re-running skips files already indexed (by source path, then by fingerprint).

Usage:
  python3 consolidate_fit_archive.py            # dry-run (default)
  python3 consolidate_fit_archive.py --execute  # actually copy
"""
import os, sys, gzip, json, hashlib
from pathlib import Path
from datetime import datetime, timezone

try:
    from fitparse import FitFile
except ImportError:
    print("Install: pip3 install --user --break-system-packages fitparse"); sys.exit(1)

EXECUTE = "--execute" in sys.argv

BASE = Path("/srv/data/physiology")
TARGET = BASE / "TheSource/fit"
INDEX = BASE / "TheSource/fit_index.json"
SRC = BASE / "sources"

GLOBS = ["*.fit", "*.fit.gz", "*.FIT", "*.FIT.gz"]
SOURCES = [
    ("wahoo",   SRC / "incoming_dropbox",   GLOBS),
    ("tpv",     SRC / "incoming_tpvirtual", GLOBS),
    ("icu",     SRC / "icu_downloads",      GLOBS),
    ("hfit",    SRC / "HealthFit",          GLOBS),
    ("tp-hist", SRC / "tp-extracted",       GLOBS),
]

index = json.loads(INDEX.read_text()) if INDEX.exists() else {"by_fingerprint": {}, "files": []}
seen_fp = set(index["by_fingerprint"].keys())
seen_paths = {entry["source_path"] for entry in index["files"]}
print(f"Resuming. Existing index has {len(seen_fp)} unique fingerprints, {len(seen_paths)} files seen.")

def read_fit(path):
    if path.name.lower().endswith(".gz"):
        with gzip.open(path, "rb") as f:
            return f.read()
    return path.read_bytes()

def fingerprint(raw):
    if len(raw) < 100:
        return None, None, None
    try:
        fit = FitFile(raw)
        sess = {}
        for msg in fit.get_messages("session"):
            for d in msg:
                if d.value is not None:
                    sess[d.name] = d.value
            break
        start = sess.get("start_time")
        if not start:
            return None, None, None
        if isinstance(start, datetime):
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            start_iso = start.astimezone(timezone.utc).isoformat()
        else:
            start_iso = str(start)
        sport = sess.get("sport") or "unknown"
        elapsed = int(sess.get("total_elapsed_time") or 0)
        distance = int(sess.get("total_distance") or 0)
        fp = f"{start_iso}|{elapsed}|{distance}|{sport}"
        return fp, str(sport), start_iso
    except Exception:
        return None, None, None

def discover_files():
    for tag, root, globs in SOURCES:
        if not root.exists():
            print(f"  note: source root absent (ok for tp-hist): {root}")
            continue
        for pat in globs:
            for f in sorted(root.rglob(pat)):
                if f.is_file():
                    yield tag, f

print("\n=== Discovery ===")
all_files = list(discover_files())
print(f"Total source files found: {len(all_files)}")
by_source = {}
for tag, _ in all_files:
    by_source[tag] = by_source.get(tag, 0) + 1
for tag, n in by_source.items():
    print(f"  {tag}: {n}")

print("\n=== Processing ===")
copied, skipped_dup, failed = 0, 0, 0
new_entries = []
for i, (tag, path) in enumerate(all_files, 1):
    if i % 200 == 0:
        print(f"  {i}/{len(all_files)} | copied={copied} dup={skipped_dup} fail={failed}")
    src_str = str(path)
    if src_str in seen_paths:
        continue
    try:
        raw = read_fit(path)
    except Exception:
        failed += 1
        continue
    fp, sport, start_iso = fingerprint(raw)
    if not fp:
        failed += 1
        continue
    if fp in seen_fp:
        skipped_dup += 1
        seen_paths.add(src_str)
        index["files"].append({
            "source_path": src_str,
            "source_tag": tag,
            "fingerprint": fp,
            "deduped_against": index["by_fingerprint"][fp]["canonical_name"],
            "copied": False,
        })
        continue
    dt = datetime.fromisoformat(start_iso)
    yyyy = dt.strftime("%Y")
    stem = dt.strftime("%Y-%m-%d_%H%M%S")
    h = hashlib.sha256(raw).hexdigest()[:8]
    canon_name = f"{stem}_{sport}_{tag}_{h}.fit"
    target_year = TARGET / yyyy
    target_year.mkdir(parents=True, exist_ok=True)
    target = target_year / canon_name
    if EXECUTE:
        target.write_bytes(raw)
    new_entries.append({
        "source_path": src_str,
        "source_tag": tag,
        "canonical_name": canon_name,
        "canonical_path": str(target),
        "fingerprint": fp,
        "sport": sport,
        "start_iso": start_iso,
        "size_bytes": len(raw),
    })
    seen_fp.add(fp)
    seen_paths.add(src_str)
    index["by_fingerprint"][fp] = {"canonical_name": canon_name, "source_tag": tag}
    copied += 1

index["files"].extend(new_entries)

if EXECUTE:
    INDEX.write_text(json.dumps(index, indent=2))
    print(f"\nIndex saved: {INDEX}")

print(f"\n=== Done ===")
print(f"Copied:    {copied}")
print(f"Dedup hit: {skipped_dup}")
print(f"Failed:    {failed}")
if not EXECUTE:
    print("\n[DRY-RUN] Re-run with --execute to actually copy.")
