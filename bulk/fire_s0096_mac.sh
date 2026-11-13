#!/bin/bash
# Fire the sector-96 bulk screen on Dev's Mac. Idempotent: safe to run
# repeatedly (the watcher cron polls every 15 min until the Mac wakes).
# Exits 0 with a clear status line in every case; only fires once.
#
# Preconditions (all checked here, nothing assumed):
#   1. S96 target-list build finished on the VM (3 files present).
#   2. Mac reachable over SSH (tunnel proxy + persistent known_hosts).
#   3. Driver not already running on the Mac.
#   4. Mac pipeline copies md5-current (bulk_screen.py, hunter.py,
#      run_chunked.py) -- the S98 lesson: a stale hunter.py crashes
#      the merge. Stale copies are re-copied, never trusted.
#   5. >= 100 GB free on /Volumes/NVME.
# On success: copies target-list files (md5-verified), fires the
# chunked driver under caffeinate, logs the PIDs, and prints FIRED.
set -u
VMROOT="$HOME/workspace/exoplanet-hunter"
MACROOT="/Volumes/NVME/pingu-jobs/exoplanet-hunter"
LOG="$HOME/workspace/goals/exoplanet-hunter/hidden_files/s96-fire.log"
SSH="ssh -o UserKnownHostsFile=/home/hatch/.ssh/known_hosts -o ProxyCommand=\"python3 $HOME/workspace/pi4/proxy-connect.py %h %p\" -o ConnectTimeout=20 -i $HOME/.ssh/id_ed25519 dk@100.67.65.120"
SCP="scp -o UserKnownHostsFile=/home/hatch/.ssh/known_hosts -o ProxyCommand=\"python3 $HOME/workspace/pi4/proxy-connect.py %h %p\" -o ConnectTimeout=20 -i $HOME/.ssh/id_ed25519"

say() { echo "$(date '+%F %T %Z') $*" | tee -a "$LOG"; }

# 1. Build finished?
for f in s0096.csv s0096_tic.csv s0096_window_default.json; do
  if [ ! -f "$VMROOT/bulk/cache/target_lists/$f" ]; then
    say "WAIT build not finished (missing $f)"
    exit 0
  fi
done

# 2. Mac reachable?
if ! eval "$SSH 'true'" 2>/dev/null; then
  say "WAIT Mac unreachable (asleep)"
  exit 0
fi

# 3. Already running?
if eval "$SSH 'pgrep -f \"run_chunked.py --sector 96\" >/dev/null'" 2>/dev/null; then
  say "ALREADY_RUNNING driver is live on the Mac"
  exit 0
fi

# 4. Pipeline copies current? (re-copy any stale file, then re-verify)
for pair in "bulk_screen.py:bulk_screen.py" "hunter.py:hunter.py" "bulk/run_chunked.py:bulk/run_chunked.py"; do
  vmfile="${pair%%:*}"; macfile="${pair##*:}"
  vm_md5=$(md5sum "$VMROOT/$vmfile" | cut -d' ' -f1)
  mac_md5=$(eval "$SSH 'md5 -q $MACROOT/$macfile 2>/dev/null || echo MISSING'" 2>/dev/null)
  if [ "$vm_md5" != "$mac_md5" ]; then
    say "COPY $vmfile (mac md5 $mac_md5 != vm $vm_md5)"
    eval "$SCP \"$VMROOT/$vmfile\" \"dk@100.67.65.120:$MACROOT/$macfile\"" || { say "FAIL scp $vmfile"; exit 1; }
    mac_md5=$(eval "$SSH 'md5 -q $MACROOT/$macfile'" 2>/dev/null)
    if [ "$vm_md5" != "$mac_md5" ]; then say "FAIL md5 mismatch after copy: $vmfile"; exit 1; fi
  fi
done
# bulk_screen.py lives at repo root on the VM; the Mac driver also
# imports it from bulk/ -- keep the Mac's bulk/bulk_screen.py in sync.
vm_md5=$(md5sum "$VMROOT/bulk_screen.py" | cut -d' ' -f1)
mac_md5=$(eval "$SSH 'md5 -q $MACROOT/bulk/bulk_screen.py 2>/dev/null || echo MISSING'" 2>/dev/null)
if [ "$vm_md5" != "$mac_md5" ]; then
  say "COPY bulk_screen.py -> Mac bulk/bulk_screen.py"
  eval "$SCP \"$VMROOT/bulk_screen.py\" \"dk@100.67.65.120:$MACROOT/bulk/bulk_screen.py\"" || { say "FAIL scp bulk/bulk_screen.py"; exit 1; }
fi

# 5. Disk space (>= 100 GB free on the NVMe volume).
free_gb=$(eval "$SSH 'df -g /Volumes/NVME | tail -1 | tr -s \" \" | cut -d\" \" -f4'" 2>/dev/null)
if [ "${free_gb:-0}" -lt 100 ]; then
  say "FAIL only ${free_gb:-?} GB free on /Volumes/NVME"
  exit 1
fi

# Copy target-list files, md5-verified.
for f in s0096.csv s0096_tic.csv s0096_window_default.json; do
  eval "$SCP \"$VMROOT/bulk/cache/target_lists/$f\" \"dk@100.67.65.120:$MACROOT/bulk/cache/target_lists/$f\"" || { say "FAIL scp $f"; exit 1; }
  vm_md5=$(md5sum "$VMROOT/bulk/cache/target_lists/$f" | cut -d' ' -f1)
  mac_md5=$(eval "$SSH 'md5 -q $MACROOT/bulk/cache/target_lists/$f'" 2>/dev/null)
  if [ "$vm_md5" != "$mac_md5" ]; then say "FAIL md5 mismatch: $f"; exit 1; fi
done
say "target-list files copied + md5-verified"

# Fire under caffeinate (the S97/S98 pattern).
eval "$SSH 'cd $MACROOT && nohup caffeinate -s -i bulk/.venv-mac/bin/python bulk/run_chunked.py --sector 96 > bulk/run_s0096_console.log 2>&1 & echo started'" || { say "FAIL fire"; exit 1; }
sleep 15
pids=$(eval "$SSH 'pgrep -fl \"run_chunked.py --sector 96\"'" 2>/dev/null)
if [ -z "$pids" ]; then
  say "FAIL driver not alive 15s after fire; console tail:"
  eval "$SSH 'tail -20 $MACROOT/bulk/run_s0096_console.log'" 2>/dev/null | tee -a "$LOG"
  exit 1
fi
say "FIRED sector-96 driver on the Mac: $pids"
