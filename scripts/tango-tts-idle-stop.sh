#!/usr/bin/env bash
#
# tango-tts-idle-stop.sh — Stop the F5-TTS sidecar when it has been idle.
#
# Intended to be run via cron or a systemd timer to conserve GPU memory.
# The F5-TTS server touches an activity stamp on every synthesis request;
# this script compares that stamp's age against the idle threshold and stops
# tango-tts.service if it has been quiet for too long. The backend will
# lazy-start the service again on the next Jeremiah synthesis request.
#
# Suggested cron entry (every 15 minutes):
#   */15 * * * * /opt/Project-Tango/scripts/tango-tts-idle-stop.sh
#
set -euo pipefail

UNIT="${TANGO_TTS_UNIT:-tango-tts.service}"
STAMP="${TANGO_F5_TTS_ACTIVITY_STAMP:-/tmp/tango-tts-last-synthesize}"
IDLE_SECONDS="${TANGO_TTS_IDLE_SECONDS:-2700}"  # 45 minutes

if ! systemctl is-active --quiet "$UNIT"; then
  exit 0
fi

now=$(date +%s)
if [ -e "$STAMP" ]; then
  last=$(stat -c %Y "$STAMP")
else
  # No stamp yet — compute age from when the service started.
  active_usec=$(systemctl show -p ActiveEnterTimestampMonotonic --value "$UNIT")
  uptime_usec=$(awk '{ printf "%.0f", $1 * 1000000 }' /proc/uptime)
  active_age=$(( (uptime_usec - active_usec) / 1000000 ))
  last=$(( now - active_age ))
fi

age=$(( now - last ))
if [ "$age" -ge "$IDLE_SECONDS" ]; then
  echo "Stopping $UNIT: idle for ${age}s (threshold ${IDLE_SECONDS}s)"
  systemctl stop "$UNIT"
fi