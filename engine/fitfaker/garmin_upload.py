#!/srv/scrapers/fitfaker/venv/bin/python
"""Upload ONE already-Garmin-identified FIT to Garmin Connect with the saved session (bypasses fit-file-faker's re-encode). Usage: garmin_upload.py <file.fit>"""
import sys, garth
garth.resume("/srv/scrapers/fitfaker/.cache/FitFileFaker/.garth")
with open(sys.argv[1], "rb") as f: r = garth.client.upload(f)
print("upload response:", r)
