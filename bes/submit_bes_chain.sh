#!/usr/bin/env bash
# Submit a resumable BES fetch across a shot-list range as a PBS dependency
# chain: chunk N+1 starts (afterany) when chunk N ends, so only ~1-2 jobs are
# ever active (respects per-user queue limits) and they run back-to-back.
#
# BES fetch is idempotent (bes_shot_complete skips already-written shots), so:
#   - a preempted chunk simply resumes on any later run,
#   - re-running this whole script at the end sweeps up anything a preemption
#     skipped.
#
# Defaults target the MODERN portion of Current_labeled_dset_highest_tol.txt
# (indices 1847:9890 = shots >= 150000), which the June-23 FDP index covers.
# Old shots (<150000, indices 0:1846) are NOT in that index and must be fetched
# via a refreshed index or a GA/D3D-direct host.
#
# Usage:
#   bash submit_bes_chain.sh                # modern range, chunk=800
#   START=1847 STOP=9890 CHUNK=800 bash submit_bes_chain.sh
set -euo pipefail
cd "$(dirname "$0")"

SHOT_LIST="${SHOT_LIST:-/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/shot_lists/Current_labeled_dset_highest_tol.txt}"
BES_RAW_ROOT="${BES_RAW_ROOT:-/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/BES_Raw}"
START="${START:-1847}"
STOP="${STOP:-9890}"
CHUNK="${CHUNK:-800}"
BES_WORKERS="${BES_WORKERS:-16}"
QUEUE="${QUEUE:-preemptable}"
WALLTIME="${WALLTIME:-06:00:00}"
ACCOUNT="${ACCOUNT:-<YOUR_PROJECT>}"
mkdir -p "$HOME/pbs"

echo "BES chain: shots list=$SHOT_LIST"
echo "  range [$START:$STOP]  chunk=$CHUNK  workers=$BES_WORKERS  queue=$QUEUE  walltime=$WALLTIME"

PREV=""
s="$START"
while [ "$s" -lt "$STOP" ]; do
  e=$(( s + CHUNK )); [ "$e" -gt "$STOP" ] && e="$STOP"
  STAMP=$(printf "%05d_%05d" "$s" "$e")
  OUT="$HOME/pbs/bes_chain_${STAMP}.out"
  ERR="$HOME/pbs/bes_chain_${STAMP}.err"
  DEP=""
  [ -n "$PREV" ] && DEP="-W depend=afterany:${PREV}"
  # shellcheck disable=SC2086
  JOB=$(qsub \
    -q "$QUEUE" \
    -l "select=1:ncpus=32:mem=200gb,walltime=${WALLTIME},filesystems=home:eagle" \
    -A "$ACCOUNT" \
    -o "$OUT" -e "$ERR" \
    -N "bes_${s}" \
    $DEP \
    -v "SHOT_LIST=${SHOT_LIST},BES_RAW_ROOT=${BES_RAW_ROOT},BATCH_START=${s},BATCH_END=${e},BES_WORKERS=${BES_WORKERS}" \
    run_bes.pbs)
  echo "  queued chunk [$s:$e] -> $JOB ${DEP:+(after $PREV)}"
  PREV="$JOB"
  s="$e"
done
echo "Chain submitted. Tail newest log:"
echo "  tail -f \$(ls -1t \$HOME/pbs/bes_chain_*.out | head -1)"
echo "Stop the chain: qdel the queued (dependent) jobs; running one finishes."
