#!/bin/bash
# Mirror the NAS Wahoo inbox (Dropbox Cloud Sync target) to mp100; fit-file-faker (monitor mode) uploads each NEW file to Garmin.
rsync -a --ignore-existing --rsync-path=/usr/bin/rsync $NAS_SSH:/volume1/Cycling/FitFileFaker/FITfiles/incoming_dropbox/ /srv/data/physiology/fitfaker/inbox/
