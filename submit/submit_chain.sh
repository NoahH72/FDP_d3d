#!/bin/bash
# submit_chain.sh — chain batches of FetchRawDataChannelWise.py (job 2 starts after job 1 ok, etc.)
#
# Usage:
#   ./submit_chain.sh
#
# Configure batch size and total shots at the top. Run from repo root.
# Requires: toksearch_submit on PATH (e.g. module load toksearch/...).
#
# Optional: set CLEAN_SHOTS_FILE to your shot list path; if set and file exists,
# TOTAL_SHOTS is derived from it (line count). Otherwise TOTAL_SHOTS below is used.
# e.g. CLEAN_SHOTS_FILE=/mnt/beegfs/users/harrisn/shot_lists/Current_labeled_dset_highest_tol.txt

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Config: change these as needed ---
BATCH_SIZE=500
TOTAL_SHOTS=5000

# Optional: derive TOTAL_SHOTS from clean shots file (same as paths_config.clean_shots_file)
if [ -n "${CLEAN_SHOTS_FILE:-}" ] && [ -f "$CLEAN_SHOTS_FILE" ]; then
  TOTAL_SHOTS=$(wc -l < "$CLEAN_SHOTS_FILE")
  # CSV shot lists (e.g. plasma_shots_only.csv) include a header row; the
  # Python loader in paths_config.py skips it, so subtract it here too.
  case "$CLEAN_SHOTS_FILE" in
    *.csv|*.CSV) TOTAL_SHOTS=$(( TOTAL_SHOTS - 1 )) ;;
  esac
  echo "Using TOTAL_SHOTS=$TOTAL_SHOTS from $CLEAN_SHOTS_FILE"
fi

PREV_JOB=""
for START in $(seq 0 $BATCH_SIZE $((TOTAL_SHOTS - 1))); do
  END=$((START + BATCH_SIZE))
  if [ "$END" -gt "$TOTAL_SHOTS" ]; then END=$TOTAL_SHOTS; fi

  if [ -z "$PREV_JOB" ]; then
    PREV_JOB=$(sbatch --parsable \
      --export=ALL,BATCH_START=$START,BATCH_END=$END \
      toksearch_submit -N 4 FetchRawDataChannelWise.py -- --ray)
  else
    PREV_JOB=$(sbatch --parsable --dependency=afterok:$PREV_JOB \
      --export=ALL,BATCH_START=$START,BATCH_END=$END \
      toksearch_submit -N 4 FetchRawDataChannelWise.py -- --ray)
  fi
  echo "Submitted batch $START:$END as job $PREV_JOB"
done

echo "Done. All batches chained (each depends on previous completing successfully)."
