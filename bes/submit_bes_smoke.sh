#!/usr/bin/env bash
# Submit a 1-shot BES smoke test through FDP on Polaris.
#
# Mirrors submit_fdp_smoke.sh (which does the same for ECEI). Goal: confirm
# end-to-end that
#   login-node proxy  ->  fdp run wrapper  ->  toksearch/PtData  ->  Ray
#   ->  bes_fetch.write_bes_shot  ->  per-shot HDF5
# all works on a single known-good plasma shot before scaling up.
#
# Prerequisites (login node):
#   screen -dmS fdp_proxy python3 /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/scripts/https_proxy.py
#   screen -ls   # verify fdp_proxy is alive
#
# Usage:
#   cd /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/ECEI-Data/bes_polaris && bash submit_bes_smoke.sh
#
set -euo pipefail
cd "$(dirname "$0")"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_LOG="${HOME}/pbs/bes_smoke_${STAMP}.out"
ERR_LOG="${HOME}/pbs/bes_smoke_${STAMP}.err"
mkdir -p "${HOME}/pbs"

# Same shot list used by submit_fdp_smoke.sh — these shots are known-good
# (142170 in particular has been verified end-to-end against PTDATA).
SMOKE_SHOTS="${SMOKE_SHOTS:-/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/shot_lists/fdp_smoke_test.txt}"
OUT_DIR="${BES_RAW_ROOT:-/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/BES_Raw_SmokeTest}"
mkdir -p "$OUT_DIR"

# Default: fetch the first shot only. Override with BATCH_END to grab more.
BATCH_START="${BATCH_START:-0}"
BATCH_END="${BATCH_END:-1}"
BES_WORKERS="${BES_WORKERS:-2}"

echo "Logs (stdout):  $OUT_LOG"
echo "Logs (stderr):  $ERR_LOG"
echo "Shot list:      $SMOKE_SHOTS"
echo "Output root:    $OUT_DIR"
echo "Slice:          [$BATCH_START:$BATCH_END]  workers=$BES_WORKERS"

qsub \
  -q debug \
  -l "select=1:ncpus=4:mem=32gb,walltime=01:00:00,filesystems=home:eagle" \
  -A <YOUR_PROJECT> \
  -o "$OUT_LOG" \
  -e "$ERR_LOG" \
  -N "bes_smoke" \
  -v "SHOT_LIST=${SMOKE_SHOTS},BES_RAW_ROOT=${OUT_DIR},BATCH_START=${BATCH_START},BATCH_END=${BATCH_END},BES_WORKERS=${BES_WORKERS}" \
  run_bes.pbs

echo ""
echo "Submitted. Monitor:"
echo "  qstat -u \$USER"
echo "  tail -f $OUT_LOG"
echo ""
echo "Expected on success: $OUT_DIR/142xxx/142170.h5  (~150 MB)"
