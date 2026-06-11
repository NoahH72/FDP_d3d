#!/bin/bash
# Submit a minimal ECEI channelwise job (2 shots by default). Run from Polaris login.
#
# Before submitting:
#   1. (Recommended) bash install_fdp_polaris.sh  — FDP pixi env + toksearch_d3d + numba
#      Or: module load conda && conda activate toksearch
#   2. Fill in ECEI-Data/polaris_ptdata.env with real PTDATA paths
#      (ask your PI or ALCF support for PTDATA_ROOT, TOKSEARCH_INDEX_*)
#
# Override shots: BATCH_START=0 BATCH_END=5 ./submit_test_fetch.sh
#
# Debug queue (if #PBS -q small is denied), set e.g.:
#   PBS_EXTRA='-q debug -l select=1:ncpus=4:mem=32gb,walltime=01:00:00,filesystems=eagle -A <YOUR_PROJECT>'
#   ./submit_test_fetch.sh
set -euo pipefail
cd "$(dirname "$0")"
# PBS stdout/stderr under $HOME/pbs — not under /eagle/<YOUR_PROJECT> (short paths, personal quota)
mkdir -p "${HOME}/pbs"
BATCH_START="${BATCH_START:-0}"
BATCH_END="${BATCH_END:-2}"
# shellcheck disable=SC2086
qsub ${PBS_EXTRA:-} \
  -o "${HOME}/pbs/ecei_channelwise.out" \
  -e "${HOME}/pbs/ecei_channelwise.err" \
  -v "BATCH_START=${BATCH_START},BATCH_END=${BATCH_END}" \
  run_batch_channelwise.pbs
echo "Submitted: shots ${BATCH_START} to ${BATCH_END} (index range, not shot numbers)"
echo "Logs: tail -f ${HOME}/pbs/ecei_channelwise.out"
