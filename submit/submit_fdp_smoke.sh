#!/usr/bin/env bash
# Submit a small FDP-backed ECEI job using shots known good from ptdata smoke tests.
#
# Prerequisites (login node):
#   screen -dmS fdp_proxy python3 /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/scripts/https_proxy.py
#   screen -ls   # verify fdp_proxy
#
# Usage:
#   cd /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/ECEI-Data && bash submit_fdp_smoke.sh
#
set -euo pipefail
cd "$(dirname "$0")"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_LOG="${HOME}/pbs/ecei_smoke_${STAMP}.out"
ERR_LOG="${HOME}/pbs/ecei_smoke_${STAMP}.err"
mkdir -p "${HOME}/pbs"

SMOKE_SHOTS="${SMOKE_SHOTS:-/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/shot_lists/fdp_smoke_test.txt}"
OUT_DIR="${OUTPUT_DIR:-/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/ECEI_Assembled_SmokeTest}"
mkdir -p "$OUT_DIR"

echo "Logs: $OUT_LOG"
echo "Err:  $ERR_LOG"
echo "Shots file: $SMOKE_SHOTS"
echo "Output dir: $OUT_DIR"

qsub \
  -q debug \
  -l "select=1:ncpus=4:mem=32gb,walltime=01:00:00,filesystems=eagle" \
  -A <YOUR_PROJECT> \
  -o "$OUT_LOG" \
  -e "$ERR_LOG" \
  -v "BATCH_START=0,BATCH_END=2,CLEAN_SHOTS_FILE=${SMOKE_SHOTS},OUTPUT_DIR=${OUT_DIR}" \
  run_batch_channelwise.pbs

echo "Submitted. Monitor: tail -f $OUT_LOG"
