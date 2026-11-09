#!/bin/bash
# One node of a Mirnov job 2 capacity job (code/run_cap_t2.pbs): claims slices from the top of the J2 series and runs each
# through code/run_slice_t2.pbs unchanged. chain_driver_t2.sh works up from the bottom through NEXT, so the two meet.
# Claim = atomic rename J2_sNNN.txt -> JC_sNNN.txt, which removes the slice from the driver's sight. Never claims within
# 2 of NEXT. Output goes to work/logs/J2_sNNN.pbs.out, so the driver promotes after it and sees its alerts.
# A slice may take up to 2 h here. `fdp run` starts per slice, so a token refreshed during the job is picked up.
# Stops on: work/STOP_CHAIN, no slices left, under 20 min of the job left, token too short for the next slice.
# Args: node_index job_end_epoch job_id. Lanes: work/chain_state_t2/LANES_CAP (default 32).
set -u
H=/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>; R=${MIRNOV_R:-$H/mirnov_2026-10}; S=$R/work/slices; ST=$R/work/chain_state_t2
RUN=${MIRNOV_RUN:-$R/code/run_slice_t2.pbs}; I=$1; END=$2; JB=$3
say() { echo "$(date -Is) worker $I $(hostname): $*"; }
while true; do
  [ -f $R/work/STOP_CHAIN ] && { say "STOP_CHAIN"; exit 0; }
  LEFT=$((END - $(date +%s) - 120)); [ $LEFT -lt 1200 ] && { say "under 20 min left"; exit 0; }
  W=$((LEFT < 7200 ? LEFT : 7200))
  python3 $H/fdp-2026-10/token_status.py $(echo $W | awk '{printf "%.2f", $1/3600 + 0.35}') >/dev/null 2>&1 || { say "token too short for ${W}s"; exit 0; }
  NEXT=$(cat $ST/NEXT); K=""
  for F in $(ls -r $S/J2_s[0-9][0-9][0-9].txt 2>/dev/null); do
    N=$(basename $F .txt); N=${N#J2_s}
    [ $((10#$N)) -ge $((NEXT + 2)) ] || break
    mv $F $S/JC_s$N.txt 2>/dev/null && { K=$N; break; }
  done
  [ -n "$K" ] || { say "no slices left to claim (NEXT=$NEXT)"; exit 0; }
  say "slice $K wall ${W}s lanes $(cat $ST/LANES_CAP 2>/dev/null || echo 32)"
  PBS_JOBID=${JB}n${I}s$K CHUNK=JC SLICE=$K CHAIN=0 LANES=$(cat $ST/LANES_CAP 2>/dev/null || echo 32) RAW_EVERY=20 Q=capacity \
    WALL=$(printf "%02d:%02d:%02d" $((W/3600)) $((W%3600/60)) $((W%60))) bash $RUN > $R/work/logs/J2_s$K.pbs.out 2>&1
  say "slice $K done rc=$?"
done
