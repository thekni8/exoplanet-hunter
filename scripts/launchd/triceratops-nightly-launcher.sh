#!/bin/bash
# TRICERATOPS golden nightly — launchd launcher (fixes round 1).
#
# WHY THIS EXISTS: the P4-8 plist put everything launchd touches at
# spawn time on the external NVMe volume (program, working directory,
# stdout/stderr). At 03:00 on 2026-11-18 the Mac was in clamshell
# sleep, the NVMe volume was inaccessible (Finder: "Bad volume:
# /Volumes/NVME" 02:40-04:35; disk re-appeared 05:11), and launchd
# could not open the stdout path:
#   "Service could not initialize: Unable to open stdout path
#    (.../phase4-p48/nightly.log), error 0x1 - Operation not permitted"
# The spawn failed -> exit 78 EX_CONFIG. The job never started: no
# log, no receipt. The nightly script itself returns only 0/1, so
# the 78 came from the spawn chain, not the script.
#
# THIS LAUNCHER + the plist's log path live on the INTERNAL disk,
# which is always accessible at spawn time. The launcher waits for
# the NVMe volume to appear (up to NIGHTLY_WAIT_HOURS, default 9 —
# 03:00 trigger -> noon deadline), then execs the real nightly under
# caffeinate (which holds the Mac awake for the run). If the volume
# never appears, it exits 1 with a VOLUME_WAIT_TIMEOUT line in the
# log; the missed-run alert (VM cron, 13:00 IST) covers notification.
#
# Run-time semantics (recorded honestly): the 03:00 calendar trigger
# fires during sleep; the nightly itself runs when the volume is
# available, typically at the morning wake. The receipt is
# timestamped at the actual run. A true 03:00 execution would need a
# scheduled wake (pmset, needs Dev's sudo) — noted as the
# alternative in FIXES_ROUND1_RECORD.md, not implemented here.
#
# TEST SEAMS (env, unset in production):
#   NIGHTLY_VOLUME          mount point to wait for (default /Volumes/NVME)
#   NIGHTLY_REPO            repo root (default $NIGHTLY_VOLUME/pingu-jobs/exoplanet-hunter)
#   NIGHTLY_WAIT_HOURS      max wait in hours (default 9)
#   NIGHTLY_WAIT_SECONDS    max wait in seconds; overrides
#                           NIGHTLY_WAIT_HOURS (tests only)
#   NIGHTLY_POLL_S          poll interval in seconds (default 60)
#   NIGHTLY_READY_FILE      if set, the volume check is `test -f` on
#                           this file instead of the mount table
#                           (lets tests fake a volume appearing)
#   NIGHTLY_EXEC_CMD        if set, run this (via eval) instead of
#                           execing the real nightly (tests only)
set -u

VOLUME="${NIGHTLY_VOLUME:-/Volumes/NVME}"
REPO="${NIGHTLY_REPO:-$VOLUME/pingu-jobs/exoplanet-hunter}"
WAIT_HOURS="${NIGHTLY_WAIT_HOURS:-9}"
if [ -n "${NIGHTLY_WAIT_SECONDS:-}" ]; then
    WAIT_SECONDS="$NIGHTLY_WAIT_SECONDS"
else
    WAIT_SECONDS=$((WAIT_HOURS * 3600))
fi
POLL_S="${NIGHTLY_POLL_S:-60}"
READY_FILE="${NIGHTLY_READY_FILE:-}"
EXEC_CMD="${NIGHTLY_EXEC_CMD:-}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] launcher: $*"; }

volume_ready() {
    if [ -n "$READY_FILE" ]; then
        [ -f "$READY_FILE" ] && return 0 || return 1
    fi
    # Mount-table check first: pure kernel state, no I/O to the
    # volume, cannot hang on an unresponsive device.
    mount | grep -q "on $VOLUME (" || return 1
    # Then confirm the repo is actually readable.
    [ -x "$REPO/.venv/bin/python" ] \
        && [ -f "$REPO/scripts/triceratops_golden_nightly.py" ]
}

START_EPOCH=$(date +%s)
DEADLINE_EPOCH=$((START_EPOCH + WAIT_SECONDS))
log "started (pid $$); waiting for $VOLUME, deadline $(date -r $DEADLINE_EPOCH '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date -d "@$DEADLINE_EPOCH" '+%Y-%m-%d %H:%M:%S %Z')"

WAITED=0
while ! volume_ready; do
    NOW=$(date +%s)
    if [ "$NOW" -ge "$DEADLINE_EPOCH" ]; then
        log "VOLUME_WAIT_TIMEOUT: $VOLUME not available after ${WAIT_SECONDS}s; exiting 1 (missed-run alert will fire)"
        exit 1
    fi
    WAITED=$((WAITED + POLL_S))
    # Log hourly while waiting (and once at the start of the wait).
    if [ "$WAITED" -eq "$POLL_S" ] || [ $((WAITED % 3600)) -lt "$POLL_S" ]; then
        log "waiting for $VOLUME (${WAITED}s elapsed, deadline in $((DEADLINE_EPOCH - NOW))s)"
    fi
    sleep "$POLL_S"
done

log "volume ready after ${WAITED}s; starting nightly in $REPO"
if [ -n "$EXEC_CMD" ]; then
    # Test seam only: run the stand-in command without cd-ing
    # (the test repo path does not exist); do not exec.
    eval "$EXEC_CMD"
    exit $?
fi
cd "$REPO" || { log "FATAL: cannot cd to $REPO"; exit 1; }
exec /usr/bin/caffeinate -s -i \
    "$REPO/.venv/bin/python" \
    scripts/triceratops_golden_nightly.py \
    --inputs-dir vetting_results/triceratops-nightly-inputs
