# BES (Beam Emission Spectroscopy) — Standalone Fetch

> **2026-10-13:** token and proxy setup changed (no `screen` proxy, no hand-copied token). See `/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/FDP_FETCH_GUIDE.md`. Pipeline commands below are unchanged.

Self-contained 64-channel BES fetcher for DIII-D shots. Intended to run on a
machine other than the GA saga cluster (e.g. ALCF Polaris) without depending
on any of the saga `ECEI-Data` modules (`physics_config`, `physics_io`,
`paths_config`, `run_physics_download`, `resource_utils`).

## What's in this directory

| File | Purpose |
|------|---------|
| `bes_fetch.py` | Core module: BES signal definitions, dedup+float32 HDF5 writer, Ray pipeline driver |
| `run_bes.py`   | Entry-point script. Reads `SHOT_LIST`, slices by `BATCH_START/END`, fetches |
| `run_bes.pbs`  | PBS template for Polaris (`qsub run_bes.pbs`) |
| `README.md`    | This file |

## Why BES gets its own pipeline

BES is 64 channels of 1 MHz fluctuation data over ~2 s of plasma per shot —
the heaviest signal in the DIII-D archive. Two cheap fixes halve the on-disk
footprint without losing any information:

1. **Shared timebase** — all 64 channels sample at the same 1 MHz clock, so
   the time vector is identical across channels. Storing it once at the file
   level (`/times`) instead of once per channel (`/besfu01/times`,
   `/besfu02/times`, ...) saves ~350 MB per shot.
2. **`float32` data** — BES values are calibrated voltage in roughly
   `[-1, +1]`. `float64` (15 sig figs) is wasteful for what's effectively a
   4-significant-figure measurement. Casting to `float32` halves the data
   payload with no practical precision loss.

Net result: **~150 MB per shot on disk**, vs ~975 MB if written naively into
the main physics HDF5 store (which is what `physics_io.append_physics_shot`
on saga was doing — see commit history for context).

For ~9,600 plasma shots this is ~1.4 TB total instead of ~9 TB.

## Output format

Each shot lands at `{BES_RAW_ROOT}/{shot//1000}xxx/{shot}.h5`. Layout:

```
/                    attrs:
                       shot              int   shot number
                       n_channels        int   number of besfuNN groups present
                       n_samples         int   length of /times (0 if not shared)
                       sample_rate_hz    float (~1_000_000.0)
                       t_start_ms        float
                       t_end_ms          float
                       dtype             str   "float32"
                       shared_times      bool  True in the common case
                       source            str   "PTDATA"
/times               (n_samples,) float64   shared timebase, gzip-4, written ONCE
/besfu01/data        (n_samples,) float32   gzip-4
/besfu02/data        ...
...
/besfu64/data
```

In the rare event that two channels disagree on their timebase, the writer
falls back to per-channel `besfuNN/times` arrays and sets `shared_times=False`
on the file's root attributes. Reader code that handles both cases:

```python
import h5py

with h5py.File("BES_Raw/146xxx/146077.h5", "r") as f:
    if f.attrs.get("shared_times", True):
        times = f["times"][:]                            # shared (common case)
    else:
        times = f["besfu01/times"][:]                    # per-channel fallback
    data_ch1 = f["besfu01/data"][:]                      # float32
    print(f.attrs["sample_rate_hz"])                     # 1e6
```

## Requirements

- Python ≥ 3.7
- `numpy`, `h5py`, `ray`
- `toksearch` with PTDATA access for BES fast channels

BES is **PTDATA-only**; the standard MDSplus tree does not have these
channels. If your host (e.g. Polaris) does not have PTDATA mirrored, you have
three options:

1. Mirror PTDATA locally (large — full archive is many TB).
2. Run BES fetch on a GA-network host that has PTDATA, then `rsync` the
   per-shot HDF5s here.
3. Configure TokSearch with a remote MDSplus endpoint that exposes BES
   (`PtDataSignal` accepts `location="remote://..."` in newer versions).

The `run_bes.pbs` template has placeholders for the PTDATA env vars; you'll
need to fill them in for your Polaris install.

## Usage

### Pure-Python (any host)

```bash
SHOT_LIST=/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/plasma_shots_only.csv \
BES_RAW_ROOT=/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/BES_Raw \
BATCH_START=0 BATCH_END=200 \
BES_WORKERS=8 \
python run_bes.py
```

Environment:

| Variable        | Required | Default          | Meaning |
|-----------------|----------|------------------|---------|
| `SHOT_LIST`     | yes      | —                | CSV with `shot` column, or text file with one shot per line |
| `BES_RAW_ROOT`  | yes      | `./BES_Raw`      | Output root (sharded) |
| `BATCH_START`   | no       | `0`              | First index into shot list |
| `BATCH_END`     | no       | end of list      | One past last index |
| `BES_WORKERS`   | no       | `8`              | Ray worker count |
| `REQUIRE_FULL`  | no       | unset            | If `1`, only skip shots with all 64 channels already present |

### Via PBS (Polaris)

Edit `run_bes.pbs` to set your project (`-A`), queue (`-q`), python binary,
and PTDATA env vars. Then:

```bash
qsub -v SHOT_LIST=/eagle/.../shots.csv,BES_RAW_ROOT=/eagle/.../BES_Raw,BATCH_START=0,BATCH_END=200 run_bes.pbs
```

For long runs, submit a series of small chunks with dependencies. Polaris
example (analogous to the saga `submit_physics_extras_chained.sh`):

```bash
PREV=""
for ((s=0; s<9621; s+=15)); do
  e=$((s+15)); [ $e -gt 9621 ] && e=9621
  if [ -z "$PREV" ]; then
    JOB=$(qsub -v SHOT_LIST=...,BES_RAW_ROOT=...,BATCH_START=$s,BATCH_END=$e run_bes.pbs)
  else
    JOB=$(qsub -W depend=afterany:$PREV -v SHOT_LIST=...,BES_RAW_ROOT=...,BATCH_START=$s,BATCH_END=$e run_bes.pbs)
  fi
  PREV=$JOB
done
```

## Skip / idempotency

`bes_shot_complete()` is the skip predicate:

- **Default** (`min_channels=1`): a shot is "done" if its file exists, has at
  least one `besfuNN` group with non-empty data, and has either the shared
  `/times` dataset or per-channel `times` arrays. This means partial fetches
  resume safely on the next run.
- **Strict** (`REQUIRE_FULL=1`, `min_channels=64`): only skip shots with all
  64 channels written. Use this if you want to be sure no shots have only
  partial coverage.

`write_bes_shot` is also idempotent at the channel level — it never
overwrites an existing `/besfuNN` group inside an open file. To force a
re-fetch, delete the per-shot HDF5 (or the specific channel groups) first.

## Sizing notes (from saga measurements)

| Quantity            | Value |
|---------------------|-------|
| Channels per shot   | 64 |
| Samples per channel | 2,097,152 (2²¹) |
| Sample rate         | 1.000 MHz |
| Window              | ~2.1 s of plasma (typically 200–2297 ms) |
| Per-channel raw     | 16.8 MB (float64) → 8.4 MB (float32) |
| Per-channel gzip-4  | ~4.5 MB |
| **Per-shot total**  | **~150 MB on disk** (data + 1× shared times + HDF5 overhead) |
| Memory per worker   | ~5 GB in flight at peak |
| Recommended workers | 8 on a ~200 GB node (saga learned 14 was too many) |

## Provenance

This package was extracted from the saga `ECEI-Data` repository on
2026-05-21 to allow fetching BES on Polaris while the main Fusion-FM extras
chain (ECE + Thomson + Filterscope + BCI + EFIT extras) continues on saga
without BES. See the saga README / commit history for the full Fusion-FM
extras pipeline.
