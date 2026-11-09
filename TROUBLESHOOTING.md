# Troubleshooting

Symptom, cause, fix. Details in [docs/](docs/).

## Token and access

| Symptom | Cause | Fix |
|---|---|---|
| `Error code 4000: acquired token not valid for /fdp-d3d` | token issued without `storage.read`: not in the DIII-D GitHub org, or a stale browser cookie | docs/02 "Gotchas": approve in a private window |
| HTTP 401/403, or "not found" for paths that exist | expired or missing token | `python3 toolkit/token_status.py`; docs/02 |
| `$BEARER_TOKEN is set but its token is expired` | stale exported variable | `unset BEARER_TOKEN`; never export it |
| job log `token too short; stopping` (exit 3) | the job would outlive the token | owner refreshes (docs/02); restart the driver; reset `state/NEXT` to the first refused slice |
| driver log `TOKEN SHORT` | as above, at submit time | as above |
| pelican shows your password in plain text | its prompt echoes under fdp's wrapper | reset (docs/02) and `clear` the terminal |

## Reads fail

| Symptom | Cause | Fix |
|---|---|---|
| old env: **every** read `PtDataError 7: Invalid shot number`, controls too | ptdata is using the removed index `json_indexes_2026-01-13_12:22:11` | repoint `PTDATA_JSON_INDEX_DIR` to the pinned snapshot (`ptdata_index.pin_ptdata_env()`; the toolkit does it) |
| `Cannot open file ... json_indexes_2026-01-13_12:22:11 ...` | same | same |
| new env: `getservbyname failed for task 'PTSERVER'` | pointname absent, bogus, or shot has no PTDATA (ptdata fell back to GA's server) | classify from the index; if the name is listed, it is an error: check token and index |
| one worker fails every shot (`Cannot open file: pelican://.../index/json/...`, about 3 s per shot) while others work | a bad worker process | nothing to fix in place; the shots are `error` and the retry pass fetches them |
| all workers fail for 2-5 minutes, then recover | short FDP/Pelican outage | retry pass |
| `list_pointnames()` fails (`Shot.extension not found`) | not supported over FDP | use `toolkit/ptdata_index.py` |
| `times not strictly increasing` on every retry | archive defect | report; do not store that channel (docs/05) |
| MDS `TreeNNF` / `TreeNODATA` | node path wrong, or no data for that shot | check the path with `probe_mds.py` on a shot that should have it |
| TDI `DIM_OF()` fails | not supported over FDP | `MdsSignal(..., dims=("times",))` |

## Jobs, queues, nodes

| Symptom | Cause | Fix |
|---|---|---|
| `would exceed queue ...'s per-user limit of jobs in 'Q' state` | per-user queue limit (Polaris debug: 1 running + 1 queued) | wait; the driver retries every 2 min |
| proxy unreachable (exit 5) | proxy down or env vars missing | `fdp_proxy` sets `ALL_PROXY`/`all_proxy` too (XRootD ignores `https_proxy` alone); retry later |
| `failed to spawn thread ... Resource temporarily unavailable` (pixi), or a probe hangs / segfaults on a login node | login-node per-user thread limit | install and fetch on compute nodes |
| `AF_UNIX path too long` (Ray) | long TMPDIR | `export TMPDIR=/tmp/ray_${PBS_JOBID%%.*}` |
| two drivers fighting, promote crashes | a second driver started from another login node | `state/driver.lock` prevents it; kill by exact PID on the owning node |
| a driver dies when your session ends | started in the foreground | `setsid nohup ... & disown` (docs/05) |
| slices finish far earlier than walltime | a bad worker burned through the slice quickly, or the slice is too small | check the per-shot states; resize slices if all good |

## Quick checks

```bash
python3 toolkit/token_status.py 2                              # token
qstat -u $USER                                                 # jobs
tail <campaign>/logs/driver_events.log                         # driver
grep SUMMARY <campaign>/logs/<series>_s0*_*.fetch.log | tail   # per-slice results
python3 toolkit/manifest.py <store>                            # counts per state, TB
```
