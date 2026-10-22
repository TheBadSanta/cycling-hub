#!/bin/bash
# TrainingPeaks Virtual originals from TRAINER_PC (SMB share "Users") -> sources/tpv_raw for dual-recording analysis ONLY
# (TPV syncs to Garmin/TP/intervals itself). mp100, 2026-10-03.
set -uo pipefail
source <(grep -E "^(TRAINER_PC_SMB_USER|TRAINER_PC_SMB_PASS)=" /srv/_env/.env | sed 's/^\([A-Z_]*\)=\(.*\)$/\1="\2"/')
IP="TRAINER_PC_HOST"; SHARE="Users"; REMOTE_DIR="WINUSER/Documents/TPVirtual/TPV_DEVICE_ID/FITFiles"; SMB=/usr/bin/smbclient
LOCAL="/srv/data/physiology/sources/tpv_raw"; SLOW_SLEEP=300; FAST_SLEEP=30; mkdir -p "$LOCAL"
is_online() { $SMB "//$IP/$SHARE" -U "$TRAINER_PC_SMB_USER%$TRAINER_PC_SMB_PASS" -c "cd $REMOTE_DIR; ls" >/dev/null 2>&1; }
pull_files() {
  $SMB "//$IP/$SHARE" -U "$TRAINER_PC_SMB_USER%$TRAINER_PC_SMB_PASS" -c "cd $REMOTE_DIR; ls" 2>/dev/null | awk '{print $1}' | grep -iE '\.fit$' \
  | while read -r f; do [ -z "$f" ] && continue; [ -f "$LOCAL/$f" ] && continue
      $SMB "//$IP/$SHARE" -U "$TRAINER_PC_SMB_USER%$TRAINER_PC_SMB_PASS" -c "cd $REMOTE_DIR; get \"$f\" \"$LOCAL/$f\"" >/dev/null 2>&1 && echo "$(date +%F_%T) pulled: $f"; done
}
mode="SLOW"
while true; do
  if is_online; then [ "$mode" != "FAST" ] && { echo "TRAINER_PC online -> FAST mode"; mode="FAST"; }; pull_files; sleep "$FAST_SLEEP"
  else [ "$mode" != "SLOW" ] && { echo "TRAINER_PC offline -> SLOW mode"; mode="SLOW"; }; sleep "$SLOW_SLEEP"; fi
done
