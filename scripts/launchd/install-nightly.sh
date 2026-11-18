#!/bin/bash
# Install (or reinstall) the TRICERATOPS golden nightly launchd job
# on the Mac. RUN ON THE MAC, from the repo root:
#   bash scripts/launchd/install-nightly.sh
# Idempotent: safe to re-run. It copies the launcher + plist from
# this repo into ~/Library/LaunchAgents/, creates the internal-disk
# log directory (launchd does NOT create parent dirs for
# StandardOutPath — a missing dir fails the spawn with exit 78),
# unloads any old copy of the job, loads the new one, and verifies
# with plutil + launchctl print.
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LA="$HOME/Library/LaunchAgents"
LOGDIR="$HOME/Library/Logs/exoplanet-hunter"
LABEL="com.takeshi.exoplanet.triceratops-nightly"
PLIST="$LABEL.plist"

mkdir -p "$LA" "$LOGDIR"
cp "$REPO/scripts/launchd/triceratops-nightly-launcher.sh" \
   "$LA/triceratops-nightly-launcher.sh"
chmod +x "$LA/triceratops-nightly-launcher.sh"
cp "$REPO/scripts/launchd/$PLIST" "$LA/$PLIST"
plutil -lint "$LA/$PLIST"

# Unload any previous copy (ignore errors: it may not be loaded,
# or may be stuck in "spawn failed" from the 2026-11-18 exit 78).
launchctl unload "$LA/$PLIST" 2>/dev/null || true
launchctl load "$LA/$PLIST"

echo "--- launchctl print (head) ---"
launchctl print "gui/$(id -u)/$LABEL" | head -30
echo "installed: next run 03:00 local; log $LOGDIR/triceratops-nightly.log"
echo "manual test (diagnostic only, NOT proof of the fix):"
echo "  launchctl start $LABEL"
