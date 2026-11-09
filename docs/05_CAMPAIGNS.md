# 05 Campaigns: thousands of shots

How the 2026 ECEI/BES/Mirnov campaigns were run on Polaris, generalized in `toolkit/`. Numbers are from those runs.

## Layout of a campaign

```
<campaign>/                 (on the project filesystem, not in the repo)
├── campaign.env            SERIES=cer1  SPEC=<spec.json>  OUT=<store>  LANES=32  [EXTRA=...] [FDP_ENV_KIND=new]
├── shots.txt               the shot list
├── slices/cer1_s001.txt …  slice files (make_slices.py)
├── logs/                   <series>_sNNN.pbs.out, <series>_sNNN_<jobid>.fetch.log, driver.out, driver_events.log
├── state/                  NEXT, LANES (change live), driver.lock
└── STOP                    touch to stop the driver after the current loop
<store>/                    OUT: <shot//1000>xxx/<shot>.h5, _status/<shot>.json, MANIFEST.sha256, SUMMARY.json
```

## Steps

1. **Smoke test and report** (docs/04).
2. **Cut slices** sized so one slice fits the walltime with margin:
   `python3 toolkit/make_slices.py --shots shots.txt --out <store> --slices <campaign>/slices --series cer1 --size 600`
   Size = (walltime - 10 min) / (seconds per shot per node), measured in the smoke test. Shot cost varies a lot by
   era (Mirnov: 1.7 s/shot for early shots, 4-5 s for late ones at 32 lanes), so cut by era if needed.
3. **Start the driver** (login node, detached so it survives your session):
   ```bash
   setsid nohup bash toolkit/chain_driver.sh <campaign> >> <campaign>/logs/driver.out 2>&1 < /dev/null & disown
   ```
   It submits one `run_slice.pbs` job per slice whenever a queue in `QUEUES` has room, refreshes MANIFEST/SUMMARY
   after each finished slice, and stops on `STOP`, a short token, an alert line in a job log (proxy unreachable,
   token too short, Traceback, Killed, walltime exceeded) or when everything is done.
4. **Watch**: `tail <campaign>/logs/driver_events.log`, `qstat -u $USER`, `cat <store>/SUMMARY.json`, and per slice the
   `SUMMARY` line at the end of the fetch log (median good-shot seconds, errors).
5. **Retry pass** after the last slice: `make_slices.py ... --states todo,error,not_attempted --start <last+1>`, restart
   the driver. Errors that persist after two passes are real; inspect them (see failure modes) and report.
6. **Transfer** (Globus) with MANIFEST.sha256; verify at the destination with `sha256sum -c MANIFEST.sha256`; delete
   the source only after the owner confirms the transfer and the check.

## Rules learned the hard way

- **One driver per campaign.** Login nodes cannot see each other's processes (a session may land on a different login
  node), so the driver holds `state/driver.lock` with a heartbeat; a second driver refuses to start while it is
  fresh (< 10 min). Kill a driver by its exact PID on its own login node, never `pkill -f`.
- **Never edit a running driver script.** Bash reads scripts as it executes; stop, edit, restart.
- **Never run `make_slices.py` over files a running job is using**, and never renumber slices the driver has not reached
  without also resetting `state/NEXT`.
- The driver's promote/manifest step runs in the background so a long step never stalls the heartbeat.

## Queues (Polaris, 2026-11)

| Queue | Limits seen | Use |
|---|---|---|
| debug | 1 running per user + 1 queued; 1-2 nodes; 1 h | main lane; waits ~0-1 h |
| debug-scaling | 1 per user counting the running one (2 queued were accepted once); up to 10 nodes; 1 h | second lane; waits 1-7 h |
| capacity | 1-4 nodes, up to 168 h; project max_run 1, max_queued 2 | big jobs, but queued jobs waited 27+ h |
| prod | routing queue (small 10-24 nodes, medium 25-99, large 100+) | 0 "running" in prod itself is normal |

Two-node jobs waited much longer than two one-node jobs; one node per job worked best. Aurora's queues differ (docs/07).

## Lanes (worker processes per node)

Same-era Mirnov slices, one Polaris node (32 cores / 64 threads), seconds per shot = median good-shot time / lanes:

| lanes | s/shot | median channel read |
|---:|---:|---:|
| 8 | about 2x the 16-lane time | |
| 32 | 4.7-4.8 | 2.05 s |
| 48 | 3.9-4.0 | 2.6 s |
| 64 | 3.6 | 3.15 s |

Throughput keeps rising to 64 lanes, but every read slows. Whether that is the node or GA's side was not resolved, and
GA asked us to go gently, so production used 48. Compare runs by **median good-shot time / lanes**, not by the raw
wall/shots rate: failed shots finish in seconds and flatter a run. With two sites fetching at once, the load on GA adds up.

## Failure modes seen (and what they look like)

| What | Signature | Effect / handling |
|---|---|---|
| **Bad worker** | one worker process fails every shot it takes with `Cannot open file: pelican://.../index/json/...` (old env shows `PtDataError 7` on all channels), about 3 s per shot, while other workers keep fetching; sometimes recovers | most of the errors in the Mirnov runs (1 to 5 workers in about a third of slices). Shots get state error, are retried; it costs no slot time |
| **Short outage** | every worker fails a few shots within the same 2-5 minutes, on all nodes | retry |
| **Index unreadable** | `index_error` in the status | state error, retry |
| **Broken archive time base** | `times not strictly increasing`: repeated times, jumps of seconds, last sample at 0 ms, same on every retry | real archive defect: not stored; report the shot and channel. Policy used: store the good channels of the shot and mark that channel as error |
| **No data** | nothing listed in the index; canary `ip` tells no-PTDATA shot from absent diagnostic | final state, not retried |
| **Token too short** | job log `token too short; stopping` (exit 3) | the driver stops; owner refreshes; restart the driver |
| **Login node hiccups** | a login-node probe hangs; `pixi` fails with thread errors | do real work in PBS |

## Storage and quota

Check quota before a campaign (`myquota` on Polaris) and size from the smoke test. gzip level 4 without shuffle is what
the stores use; for dB/dt-type data float32+gzip was about 0.65-0.75 of the int16 size, with shuffle files got larger.
