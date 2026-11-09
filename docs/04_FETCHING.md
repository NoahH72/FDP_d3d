# 04 Fetching a signal

## Two kinds of DIII-D data

| | PTDATA | MDSplus |
|---|---|---|
| What | raw digitizer records by **pointname** (`ip`, `MPI66M067D`, `B1`, ECEI/BES channels) | analysed and diagnostic trees by **tree + node** (`EFIT01 \ipmhd`, `ELECTRONS TS.BLESSED.CORE:TEMP`, CER in `IONS`) |
| toksearch | `PtDataSignal(pointname)` | `MdsSignal(node, tree, dims=("times",))` |
| Absent or not? | the **pinned json index** lists every pointname the archive holds per shot | no index; only the error message |

```python
from toksearch import MdsSignal, Pipeline
from toksearch_d3d import PtDataSignal

pipe = Pipeline([185000])
pipe.fetch("ip", PtDataSignal("ip"))
pipe.fetch("ipmhd", MdsSignal(r"\ipmhd", "EFIT01"))
pipe.fetch("ts_te", MdsSignal("TS.BLESSED.CORE:TEMP", "ELECTRONS", dims=("times",)))
rec = pipe.compute_serial()[0]
rec.errors            # per-signal failures, keyed by name (a failure never raises; always check this)
rec["ip"]["data"], rec["ip"]["times"]
```
- `MdsSignal(..., dims=(...))` returns the dimension arrays. TDI `DIM_OF()` expressions do not work over FDP. Do not pass
  `location=`; `fdp run` points MDSplus at Pelican.
- MDS trees verified over FDP: `EFIT01`, `ELECTRONS` (Thomson), `ZIPFIT01` (old env), `IONS` (CER, see below).
- `rec.get(name, None)` needs the default argument in toksearch 2.19.
- `compute_ray()` needs a short `TMPDIR` (Ray's socket path limit is 107 bytes): `export TMPDIR=/tmp/ray_${PBS_JOBID%%.*}`.
  The toolkit uses a plain multiprocessing pool instead of Ray (simpler, and it scaled to 64 lanes per node).

## The PTDATA index, and why "absent" must come from it

FDP gives **the same exception** for an absent pointname, a shot with no PTDATA, and a short outage:
- old env (ptdata 1.4.6): `PtDataError 7: Invalid shot number (<=0 or >999999)` for all three. It is also what you get on
  *every* read if the index snapshot is wrong (the old package hard-codes `json_indexes_2026-01-13_12:22:11`, which
  was removed from the origin);
- new env (ptdata 2.11.5): `PtDataError 22: getservbyname failed for task 'PTSERVER'` (ptdata falls back to GA's own
  server, which is not reachable) for an absent pointname, a bogus pointname and a no-PTDATA shot alike.
- `list_pointnames()` does not work over FDP (`Shot.extension not found: Shot N.PLA`).

So: **read the pinned index** (`toolkit/ptdata_index.py`) and classify each channel as
`ok` (listed and fetched), `absent` (not listed), `error` (listed but the fetch or QA failed, exact text kept).
A shot with nothing listed is `no_data`; an `ip` canary fetch then tells "no PTDATA for this shot" (canary fails too)
from "this diagnostic is absent" (canary ok).

Pin one snapshot per campaign (`FDP_INDEX_SNAPSHOT` in `sites/site.env`; 2026-11: `json_indexes_2026-06-23_15:20:51`)
and record it in every output. Check what exists at the origin before moving a campaign to a newer one.

```bash
# one-shot probe (allowed on a login node): which pointnames does shot 185000 hold that match a pattern?
fdp run --device d3d python toolkit/ptdata_index.py 185000 '^MPI66M'
```

## MDSplus nodes: find them before you fetch

```bash
fdp run --device d3d python toolkit/probe_mds.py 185000 IONS "CER.CERQUICK.TANGENTIAL.CHANNEL01:TEMP" "<other nodes>"
```
prints `ok` with shapes or `FAIL` with the last error line for each node. Errors whose text says the node or its data
does not exist (`TreeNNF`, `TreeNODATA`) are classified `absent` by the toolkit with `absent_basis = "mds message"`;
everything else is `error`. See "CER" below for what was verified.

## The toolkit fetcher

`toolkit/fetch_signals.py` fetches a **signal spec** for a list of shots: one HDF5 per shot plus a status JSON per shot.

```json
{"name": "core_basic",
 "signals": {
   "ip":           {"kind": "ptdata", "pointname": "ip"},
   "efit01_ipmhd": {"kind": "mds", "tree": "EFIT01", "node": "\\ipmhd", "dims": ["times"]},
   "mirnov":       {"kind": "ptdata_regex", "pattern": "^MPI66M\\d{3}D$"}}}
```
- `ptdata_regex` expands to every index pointname matching the pattern, per shot (channel sets change between eras).
- Output: `OUT/<shot//1000>xxx/<shot>.h5` and `OUT/_status/<shot>.json`. The status file is the ledger: state
  (`fetched`, `no_data`, `error`), per-signal status, exception text, seconds, shapes, sha256 of the returned data,
  versions, code hash, host, pid, index snapshot.
- HDF5: `/<signal>/data` in the dtype returned, attributes with pointname/tree/node, units, PTDATA header fields;
  PTDATA time bases once per distinct array in `/timebases/tbN` (the signal's `timebase` attribute names it);
  MDS dims as `/<signal>/dim_<name>`.
- Files are written only for `fetched` shots (no errors), so a store holds complete shots and every error shot is retried
  later. `--keep-partial` writes shots with errors too (flagged `partial`).
- Reruns skip shots already `fetched` or `no_data` (unless `--redo`), so retrying is just running the same list again.
- `--lanes N` runs N worker processes, one shot each. `--deadline-s` stops starting new shots near the walltime.
- `--float32-checked` stores PTDATA channels as float32 only where it is provably lossless (docs/06).

Run it in PBS through `toolkit/run_slice.pbs` (proxy, token check, environment, logs) or, for many slices, the chain
driver (docs/05).

## Smoke test before any bulk run

1. Pick 10-15 shots spanning the eras you will fetch, including known oddities, plus 2 negative controls (a shot with no
   PTDATA, such as 177267, and a shot where the signal is known absent).
2. Run them in one PBS job at a few lanes. If a reference exists (data fetched another way, e.g. on GA's saga cluster),
   compare sha256 of data and times bit for bit.
3. Check per shot: channels ok vs index vs expectation, lengths, time ranges, sample rates, dtypes, absent/error counts,
   MB and seconds per shot. Project size and node-hours.
4. Report, get the go-ahead, then bulk. (examples/mirnov has full smoke tests and reports.)

## CER

Verified 2026-11-08 (new env, `probe_mds.py`, shots 165920 and 185000), tree `IONS`:

| Node | 185000 | 165920 |
|---|---|---|
| `CER.CERQUICK.TANGENTIAL.CHANNEL01:TEMP` | 440 samples, float32 | 900 |
| `CER.CERQUICK.TANGENTIAL.CHANNEL01:ROTC` | 440 | 900 |
| `CER.CERQUICK.VERTICAL.CHANNEL01:TEMP` | 544 | 10 |
| `CER.CERAUTO.TANGENTIAL.CHANNEL01:TEMP` | 429 | 900 |
| `CER.CERFIT.TANGENTIAL.CHANNEL01:TEMP` | TreeNODATA | TreeNODATA |
| `\\IONS::TOP.CER.CERQUICK.TANGENTIAL.CHANNEL01:TEMP` (full path) | same as the short form | same |

`toolkit/signals/cer_quick_example.json` holds these. Channel counts and names change between years: enumerate the
channels and analyses you need with `probe_mds.py` on shots from every era before a bulk run.
