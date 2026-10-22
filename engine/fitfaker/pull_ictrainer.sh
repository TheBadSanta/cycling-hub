#!/bin/bash
# icTrainer -> Garmin Connect (mp100, 2026-10-03; moved off the NAS after the DSM reinstall wiped its daemons):
# pull new FIT files from TRAINER_PC E:\Cycling\ICTrainer (SMB share "Cycling"), patch only the device-identity bytes
# to Garmin Edge 840 (ict_fix.py), upload directly with garth. fit-file-faker is NOT used for these (its re-encode
# corrupts icTrainer's session message -> no Primary Benefit). *_garmin.fit twins and -TP_ exports are skipped.
set -uo pipefail
source <(grep -E "^(TRAINER_PC_SMB_USER|TRAINER_PC_SMB_PASS)=" /srv/_env/.env | sed 's/^\([A-Z_]*\)=\(.*\)$/\1="\2"/')
IP="TRAINER_PC_HOST"; SHARE="Cycling"; REMOTE_DIR="ICTrainer"; SMB=/usr/bin/smbclient
BASE="/srv/data/physiology/fitfaker/ictrainer_stage"; RAW="$BASE/raw"; FIXED="$BASE/fixed"; SEEN="/srv/scrapers/fitfaker/.ictrainer_seen"
PY=/srv/scrapers/fitfaker/venv/bin/python; FIX=/srv/scrapers/fitfaker/ict_fix.py; UP=/srv/scrapers/fitfaker/garmin_upload.py
SLOW_SLEEP=300; FAST_SLEEP=30; mkdir -p "$RAW" "$FIXED"; touch "$SEEN"
list_remote() { $SMB "//$IP/$SHARE" -U "$TRAINER_PC_SMB_USER%$TRAINER_PC_SMB_PASS" -c "cd $REMOTE_DIR; ls" 2>/dev/null \
    | sed -nE 's/^  (.*[^ ])[ ]+[ADHSRNC]+[ ]+[0-9]+[ ]+[A-Z][a-z]{2} [A-Z][a-z]{2} +[0-9]+ [0-9:]{8} [0-9]{4}$/\1/p' | grep -iE '\.fit$'; }
is_online() { $SMB "//$IP/$SHARE" -U "$TRAINER_PC_SMB_USER%$TRAINER_PC_SMB_PASS" -c "cd $REMOTE_DIR; ls" >/dev/null 2>&1; }
pull_files() {
  list_remote | grep -iE "_garmin\.fit$|-TP_" | while IFS= read -r f; do grep -qxF "$f" "$SEEN" || echo "$f" >> "$SEEN"; done
  list_remote | while IFS= read -r f; do
    grep -qxF "$f" "$SEEN" && continue
    if $SMB "//$IP/$SHARE" -U "$TRAINER_PC_SMB_USER%$TRAINER_PC_SMB_PASS" -c "cd $REMOTE_DIR; get \"$f\" \"$RAW/$f\"" >/dev/null 2>&1; then
      echo "$(date +%F_%T) pulled: $f"
      if $PY "$FIX" "$RAW/$f" "$FIXED/$f" >/dev/null 2>&1; then
        out=$($PY "$UP" "$FIXED/$f" 2>&1 | tail -1 | cut -c1-160); echo "$(date +%F_%T) garmin: $out"; echo "$f" >> "$SEEN"
      else echo "$(date +%F_%T) PATCH FAILED: $f (left for retry)"; fi
    fi
  done
}
mode="SLOW"
while true; do
  if is_online; then [ "$mode" != "FAST" ] && { echo "TRAINER_PC online -> FAST mode"; mode="FAST"; }; pull_files; sleep "$FAST_SLEEP"
  else [ "$mode" != "SLOW" ] && { echo "TRAINER_PC offline -> SLOW mode"; mode="SLOW"; }; sleep "$SLOW_SLEEP"; fi
done
