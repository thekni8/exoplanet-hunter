#!/bin/bash
# Sweep-5 vetting queue — strictly sequential (RAM discipline).
cd /home/hatch/workspace/exoplanet-hunter
PY=.venv/bin/python
run() {
  tic=$1; rad=$2; p=$3; sde=$4; stamp=$5; mode=$6
  echo "=== $(date +%H:%M:%S) TIC $tic ($mode) ===" >> sweep5_logs/queue.log
  $PY sweep5_vet.py "$tic" "$rad" "$p" "$sde" "$stamp" $mode \
      > "sweep5_logs/vet_${tic}.log" 2>&1
  echo "--- exit $? TIC $tic ---" >> sweep5_logs/queue.log
}
# The five patchy — full gauntlet + uncapped era-split tiebreaker
run 349481800 0.40 19.4477 9.4  "9/17 sectors, mean depth 0.53% - patchy" "--uncapped"
run 349519662 0.48 14.7923 15.2 "9/19 sectors, mean depth 0.34% - patchy (high-contamination flag)" "--uncapped"
run 349309779 0.35 13.7215 16.5 "5/16 sectors, mean depth -0.18% - patchy" "--uncapped"
run 349268662 0.43 13.7215 10.4 "6/17 sectors, mean depth 0.01% - patchy" "--uncapped"
run 349193983 0.46 13.2094 15.0 "6/15 sectors, mean depth 0.05% - patchy (high-contamination flag)" "--uncapped"
# Trio member with fails stamp — full mode so orbit-phase + persistence run
run 349268505 0.40 13.7215 10.3 "4/16 sectors - fails persistence - blend-suspect" ""
# The ten remaining fails-persistence hits — fold completion
run 349370722 0.30 13.2045 11.6 "1/13 sectors - fails persistence - blend-suspect (high-contamination flag)" "--folds-only"
run 349370477 0.37 12.9374 12.7 "5/19 sectors - fails persistence - blend-suspect" "--folds-only"
run 349408892 0.48 24.2110 13.0 "5/18 sectors - fails persistence - blend-suspect (high-contamination flag)" "--folds-only"
run 349477874 0.45 12.7610 8.7  "4/17 sectors - fails persistence - blend-suspect" "--folds-only"
run 349370417 0.43 13.2511 18.0 "4/15 sectors - fails persistence - blend-suspect" "--folds-only"
run 349370907 0.43 23.9292 11.0 "3/18 sectors - fails persistence - blend-suspect (high-contamination flag)" "--folds-only"
run 349273239 0.37 23.5201 11.0 "3/19 sectors - fails persistence - blend-suspect (high-contamination flag)" "--folds-only"
run 349309664 0.41 13.2462 10.4 "4/15 sectors - fails persistence - blend-suspect" "--folds-only"
run 349478154 0.36 13.1335 10.7 "4/17 sectors - fails persistence - blend-suspect (high-contamination flag)" "--folds-only"
run 349193749 0.50 13.9690 12.5 "3/16 sectors - fails persistence - blend-suspect" "--folds-only"
echo "=== QUEUE DONE $(date +%H:%M:%S) ===" >> sweep5_logs/queue.log
