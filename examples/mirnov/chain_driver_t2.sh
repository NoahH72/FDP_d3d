#!/bin/bash
# Login-node driver for Mirnov job 2: one slice series work/slices/J2_sNNN.txt fed to two queues. Submits the next slice
# when a queue has room and promotes after every finished slice. Runs qsub/promote only; fetching happens in PBS jobs.
# debug: max_run 1/user but a queued successor is allowed, so it keeps one job waiting behind the running one;
# debug-scaling: max_queued 1/user counts running jobs too, so it takes a new job only when its job is gone.
# Lanes per node: work/chain_state_t2/LANES (default 32). Next slices are picked up from work/chain_state_t2/NEXT.
# Stops on: work/STOP_CHAIN, token < 1.3 h, an alert in a job log, or no slices left and no jobs running.
R=/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10; cd $R; L=work/logs; AP=$L/autopromote_t2.log; ST=work/chain_state_t2
mkdir -p $ST; [ -f $ST/NEXT ] || echo 1 > $ST/NEXT; [ -f $ST/LANES ] || echo 32 > $ST/LANES
count() { cat $L/J2_s*.pbs.out 2>/dev/null | grep -c "fetch rc"; }
alert() { cat $L/J2_s*.pbs.out 2>/dev/null | grep -cE "unreachable|token too short|Traceback|Killed|exceeded"; }
prom() { (cd code && python3 promote.py T2 ALL && python3 write_readme_t2.py && python3 promote.py rebuild T2) >> $AP 2>&1; }
# Single-driver lock (login nodes cannot see each other's processes): owner "host pid" plus a heartbeat every loop.
LK=$ST/driver.lock; ME="$(hostname) $$"
if [ -f $LK ] && [ "$(head -1 $LK)" != "$ME" ] && [ $(( $(date +%s) - $(stat -c %Y $LK) )) -lt 600 ]; then
  echo "another driver holds $LK: $(head -1 $LK)"; exit 4; fi
echo "$ME" > $LK.tmp.$$ && mv -f $LK.tmp.$$ $LK
n0=$(count); a0=$(alert); echo "$(date -u -Is) chain_driver_t2 start n0=$n0 ($ME)" >> $AP
# Promote runs in the background (it grows with the store, 15 min at 18k shots) so submitting and the heartbeat keep going.
# One at a time; slices ending meanwhile are taken by the next one. Every exit waits for a running promote.
PP=""; trap 'wait' EXIT
while true; do
  [ "$(head -1 $LK 2>/dev/null)" = "$ME" ] || { echo "lost driver lock to $(head -1 $LK)"; exit 4; }; touch $LK
  if [ -n "$PP" ] && ! kill -0 $PP 2>/dev/null; then
    wait $PP || { echo "PROMOTE FAILED"; tail -5 $AP; exit 1; }; PP=""; echo "$(date -u -Is) promoted after slice end #$PN" >> $AP; fi
  n=$(count); if [ -z "$PP" ] && [ "$n" -gt "$n0" ]; then n0=$n; PN=$n; prom & PP=$!; fi
  a=$(alert); [ "$a" -gt "$a0" ] && { echo "ALERT"; grep -hE "unreachable|token too short|Traceback|Killed|exceeded" $L/J2_s*.pbs.out | tail -3; exit 2; }
  [ -f work/STOP_CHAIN ] && { echo "STOP_CHAIN"; exit 0; }
  JOBS=$(qstat -u $USER 2>/dev/null | tail -n +6 | awk '$4 ~ /^J2s/ {print $3, $10}')
  for Q in debug debug-scaling; do
    k=$(cat $ST/NEXT); NS=$(printf %03d $k)
    [ -f work/slices/J2_s${NS}.txt ] || break
    if [ $Q = debug ]; then echo "$JOBS" | grep -qE "^debug Q" && continue
    else echo "$JOBS" | grep -qE "^debug-s" && continue; fi
    python3 /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp-2026-10/token_status.py 1.3 >/dev/null 2>&1 || { echo "TOKEN SHORT: not submitting J2_s${NS}"; exit 3; }
    out=$(qsub -q $Q -l walltime=01:00:00 -o $L/J2_s${NS}.pbs.out -N J2s${NS} \
          -v CHUNK=J2,SLICE=$k,CHAIN=0,LANES=$(cat $ST/LANES),RAW_EVERY=20,Q=$Q,WALL=01:00:00 code/run_slice_t2.pbs 2>&1) \
      && { echo $((k+1)) > $ST/NEXT; echo "$(date -u -Is) submitted J2_s${NS} on $Q: $out" >> $AP; } \
      || echo "$(date -u -Is) qsub J2_s${NS} on $Q deferred: $out" >> $AP
  done
  k=$(cat $ST/NEXT)
  if [ ! -f work/slices/J2_s$(printf %03d $k).txt ] && [ -z "$(qstat -u $USER 2>/dev/null | tail -n +6 | awk '$4 ~ /^J2s/')" ]; then sleep 60; wait; prom; echo "ALL SLICES DONE"; exit 0; fi
  sleep 120
done
