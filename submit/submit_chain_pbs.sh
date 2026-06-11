#!/bin/bash
# submit_chain_pbs.sh — chain batches of FetchRawDataChannelWise.py via PBS (Polaris).
#
# Each batch job processes BATCH_SIZE shots (index range). Job N+1 starts only after
# job N completes successfully (PBS dependency: afterok).
#
# Prerequisites:
#   1. HTTPS proxy running on a login node:
#        screen -dmS fdp_proxy python3 /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/scripts/https_proxy.py
#   2. Bearer token current: cat ~/.fdp/token | head -c 40
#
# Usage:
#   cd /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/ECEI-Data
#   bash submit_chain_pbs.sh                       # uses defaults below
#   BATCH_SIZE=250 bash submit_chain_pbs.sh        # smaller batches
#   TOTAL_SHOTS=100 bash submit_chain_pbs.sh       # quick test
#
# Derive TOTAL_SHOTS from shot list:
#   CLEAN_SHOTS_FILE=/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/shot_lists/Current_labeled_dset_highest_tol.txt \
#     bash submit_chain_pbs.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Config ---
BATCH_SIZE="${BATCH_SIZE:-500}"
TOTAL_SHOTS="${TOTAL_SHOTS:-9890}"
QUEUE="${QUEUE:-preemptable}"
WALLTIME="${WALLTIME:-24:00:00}"
NCPUS="${NCPUS:-32}"
MEM="${MEM:-200gb}"
ACCOUNT="${ACCOUNT:-<YOUR_PROJECT>}"

if [ -n "${CLEAN_SHOTS_FILE:-}" ] && [ -f "$CLEAN_SHOTS_FILE" ]; then
  TOTAL_SHOTS=$(wc -l < "$CLEAN_SHOTS_FILE")
  case "$CLEAN_SHOTS_FILE" in
    *.csv|*.CSV) TOTAL_SHOTS=$(( TOTAL_SHOTS - 1 )) ;;
  esac
  echo "Deriving TOTAL_SHOTS=$TOTAL_SHOTS from $CLEAN_SHOTS_FILE"
fi

mkdir -p "${HOME}/pbs"

echo "=== PBS Chain Submission ==="
echo "  Total shots:  $TOTAL_SHOTS"
echo "  Batch size:   $BATCH_SIZE"
echo "  Queue:        $QUEUE"
echo "  Walltime:     $WALLTIME"
echo "  Resources:    ${NCPUS} CPUs, ${MEM}"
echo "  Account:      $ACCOUNT"
echo ""

PREV_JOB=""
JOB_COUNT=0

for START in $(seq 0 "$BATCH_SIZE" $((TOTAL_SHOTS - 1))); do
  END=$((START + BATCH_SIZE))
  if [ "$END" -gt "$TOTAL_SHOTS" ]; then END=$TOTAL_SHOTS; fi

  STAMP="${START}_${END}"
  OUT_LOG="${HOME}/pbs/ecei_batch_${STAMP}.out"
  ERR_LOG="${HOME}/pbs/ecei_batch_${STAMP}.err"

  QSUB_ARGS=(
    -q "$QUEUE"
    -l "select=1:ncpus=${NCPUS}:mem=${MEM},walltime=${WALLTIME},filesystems=eagle"
    -A "$ACCOUNT"
    -o "$OUT_LOG"
    -e "$ERR_LOG"
    -v "BATCH_START=${START},BATCH_END=${END},ECEI_PROFILE=1,ECEI_TIMING=1"
  )

  if [ -n "$PREV_JOB" ]; then
    QSUB_ARGS+=(-W "depend=afterany:${PREV_JOB}")
  fi

  PREV_JOB=$(qsub "${QSUB_ARGS[@]}" run_batch_channelwise.pbs)
  JOB_COUNT=$((JOB_COUNT + 1))
  echo "  Job $JOB_COUNT: shots ${START}:${END}  ->  ${PREV_JOB}  (log: ${OUT_LOG})"
done

echo ""
echo "Submitted $JOB_COUNT chained jobs. Each depends on the previous completing successfully."
echo "Monitor: qstat -u $(whoami)"
echo "Logs:    ls ~/pbs/ecei_batch_*.out"
