#!/bin/bash
# Login-node driver for one campaign: feeds the slice series <campaign>/slices/<SERIES>_sNNN.txt to the queues in
# $QUEUES (sites/site.env), one run_slice.pbs job per slice, and refreshes MANIFEST/SUMMARY after each finished slice.
# It only runs qsub/qstat and stdlib Python; all fetching happens in PBS jobs.
#
#   setsid nohup bash toolkit/chain_driver.sh <campaign_dir> >> <campaign_dir>/logs/driver.out 2>&1 < /dev/null & disown
#
# <campaign_dir>/campaign.env must set: SERIES (<= 6 chars; job names are <SERIES>sNNN), SPEC, OUT
#   optional: LANES (default 16), EXTRA (fetch_signals options), FDP_ENV_KIND (new|old), WALL (default $WALLTIME)
# State in <campaign_dir>/state/: NEXT (next slice number), LANES (read at each submit, so it can be changed live),
#   driver.lock ("host pid", touched every loop: login nodes cannot see each other's processes, so a second driver
#   on another login node refuses to start while the heartbeat is < 10 min old).
# Stops on: <campaign_dir>/STOP, token < WALL + 0.3 h, an alert line in a job log, no slices left and no jobs.
# Never edit this file while a driver is running it (bash reads scripts as it goes); stop, edit, restart.
set -u
C=$(cd "${1:?usage: chain_driver.sh <campaign_dir>}" && pwd)
. "$(dirname "$0")/site.sh" || exit 2
# shellcheck disable=SC1091
. "$C/campaign.env"
: "${SERIES:?}" "${SPEC:?}" "${OUT:?}"
[ ${#SERIES} -le 6 ] || { echo "SERIES must be <= 6 characters"; exit 2; }
WALL=${WALL:-$WALLTIME}; L=$C/logs; ST=$C/state; LG=$L/driver_events.log
mkdir -p "$L" "$ST"; [ -f "$ST/NEXT" ] || echo 1 > "$ST/NEXT"; [ -f "$ST/LANES" ] || echo "${LANES:-16}" > "$ST/LANES"
NEED_H=$(echo "$(wall_seconds "$WALL")" | awk '{printf "%.2f", $1/3600 + 0.3}')
count() { cat "$L"/"$SERIES"_s*.pbs.out 2>/dev/null | grep -c "fetch rc"; }
ALERTS="unreachable|token too short|Traceback|Killed|exceeded"
alert() { cat "$L"/"$SERIES"_s*.pbs.out 2>/dev/null | grep -cE "$ALERTS"; }
LK=$ST/driver.lock; ME="$(hostname) $$"
if [ -f "$LK" ] && [ "$(head -1 "$LK")" != "$ME" ] && [ $(( $(date +%s) - $(stat -c %Y "$LK") )) -lt 600 ]; then
  echo "another driver holds $LK: $(head -1 "$LK")"; exit 4; fi
echo "$ME" > "$LK.tmp.$$" && mv -f "$LK.tmp.$$" "$LK"
n0=$(count); a0=$(alert); echo "$(date -u -Is) driver start series=$SERIES next=$(cat "$ST/NEXT") ($ME)" >> "$LG"
MP=""; trap 'wait' EXIT
while true; do
  [ "$(head -1 "$LK" 2>/dev/null)" = "$ME" ] || { echo "lost driver lock to $(head -1 "$LK")"; exit 4; }; touch "$LK"
  if [ -n "$MP" ] && ! kill -0 "$MP" 2>/dev/null; then wait "$MP"; MP=""; fi
  n=$(count); if [ -z "$MP" ] && [ "$n" -gt "$n0" ]; then n0=$n; python3 "$TOOLKIT_DIR/manifest.py" "$OUT" >> "$LG" 2>&1 & MP=$!; fi
  a=$(alert); [ "$a" -gt "$a0" ] && { echo "ALERT"; grep -hE "$ALERTS" "$L"/"$SERIES"_s*.pbs.out | tail -3; exit 2; }
  [ -f "$C/STOP" ] && { echo "STOP file"; exit 0; }
  JOBS=$(qstat -u "$USER" 2>/dev/null | tail -n +6 | awk -v p="^${SERIES}s" '$4 ~ p {print $3}')
  for QN in $QUEUES; do
    Q=${QN%%:*}; MAX=${QN##*:}
    k=$(cat "$ST/NEXT"); NS=$(printf %03d "$k"); SF=$C/slices/${SERIES}_s${NS}.txt
    [ -f "$SF" ] || break
    QS=$Q; [ ${#Q} -gt 8 ] && QS="${Q:0:7}*"   # qstat truncates long queue names to 7 chars + "*"
    [ "$(echo "$JOBS" | grep -cxF "$QS")" -lt "$MAX" ] || continue
    fdp_token_ok "$NEED_H" > /dev/null 2>&1 || { echo "TOKEN SHORT: not submitting ${SERIES}_s${NS}"; exit 3; }
    out=$(qsub -A "$PROJECT" -q "$Q" -l walltime="$WALL" -l filesystems="$FILESYSTEMS" -l "select=1${SELECT_EXTRA}" \
          -o "$L/${SERIES}_s${NS}.pbs.out" -N "${SERIES}s${NS}" \
          -v "REPO=$REPO_DIR,FDP_SITE_ENV=$FDP_SITE_ENV,SPEC=$SPEC,SLICE_FILE=$SF,OUT=$OUT,LANES=$(cat "$ST/LANES"),WALL=$WALL,FDP_ENV_KIND=${FDP_ENV_KIND:-new},EXTRA=${EXTRA:-}" \
          "$TOOLKIT_DIR/run_slice.pbs" 2>&1) \
      && { echo $((k + 1)) > "$ST/NEXT"; JOBS="$JOBS
$QS"; echo "$(date -u -Is) submitted ${SERIES}_s${NS} on $Q: $out" >> "$LG"; } \
      || echo "$(date -u -Is) qsub ${SERIES}_s${NS} on $Q deferred: $out" >> "$LG"
  done
  k=$(cat "$ST/NEXT")
  if [ ! -f "$C/slices/${SERIES}_s$(printf %03d "$k").txt" ] && [ -z "$(qstat -u "$USER" 2>/dev/null | tail -n +6 | awk -v p="^${SERIES}s" '$4 ~ p')" ]; then
    sleep 60; wait; python3 "$TOOLKIT_DIR/manifest.py" "$OUT" >> "$LG" 2>&1; echo "ALL SLICES DONE"; exit 0; fi
  sleep 120
done
