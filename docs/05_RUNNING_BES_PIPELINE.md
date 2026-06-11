# 05 - Running the BES Pipeline

## Goal

Fetch BES (Beam Emission Spectroscopy) 64-channel data from DIII-D and assemble it into HDF5 files on ALCF Polaris.

## Prerequisites

- FDP installed and configured ([01 - Installation](01_INSTALLATION.md))
- Proxy running on the login node ([03 - Proxy Setup](03_PROXY_SETUP.md))
- Bearer token valid and stored at `~/.fdp/token`

## Background

BES captures 64 channels of 1 MHz fluctuation data over approximately 2 seconds of plasma per shot. This is the heaviest signal in the DIII-D archive and uses a standalone pipeline separate from the ECEI pipeline.

**Key facts:**

- BES is PTDATA-only. The standard MDSplus tree does not contain these channels.
- Two optimizations halve the on-disk footprint:
  1. **Shared timebase** -- stored once instead of per-channel.
  2. **float32 casting** -- reduces from float64 without meaningful precision loss for fluctuation data.
- Result: approximately 150 MB/shot on disk instead of approximately 975 MB naively.
- For the full dataset of approximately 9600 shots: approximately 1.4 TB on disk.
- Peak memory: approximately 5 GB per worker.

**Output format:** One HDF5 file per shot at `{BES_RAW_ROOT}/{shot//1000}xxx/{shot}.h5`

```
HDF5 layout:
  Root attributes:
    shot, n_channels, n_samples, sample_rate_hz,
    t_start_ms, t_end_ms, dtype, shared_times, source

  /times           shape: (N,)         Shared timebase (ms)
  /besfuNN/data    shape: (N,)         float32, NN = 01..64
```

**Reader example:**

```python
import h5py

with h5py.File("BES_Raw/146xxx/146077.h5", "r") as f:
    if f.attrs.get("shared_times", True):
        times = f["times"][:]
    else:
        times = f["besfu01/times"][:]
    data_ch1 = f["besfu01/data"][:]
    print(f.attrs["sample_rate_hz"])
```

## Steps

### 1. Verify proxy and token

```bash
screen -ls | grep fdp_proxy   # should show a session
cat ~/.fdp/token | head -c 40   # should show JWT string
```

If either check fails, see [03 - Proxy Setup](03_PROXY_SETUP.md).

### 2. Submit a BES smoke test

```bash
cd $PROJECT_ROOT/bes
qsub -v SHOT_LIST=/path/to/your/shots.txt,BES_RAW_ROOT=/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/BES_Raw,BATCH_START=0,BATCH_END=10 run_bes.pbs
```

Replace `/path/to/your/shots.txt` with the path to your shot list file (CSV with a `shot` column, or a text file with one shot per line).

### 3. Or run directly with Python

```bash
SHOT_LIST=/path/to/shots.txt \
BES_RAW_ROOT=/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/BES_Raw \
BATCH_START=0 BATCH_END=10 \
BES_WORKERS=8 \
python bes/run_bes.py
```

## Key Environment Variables

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `SHOT_LIST` | yes | -- | CSV with `shot` column, or text file with one shot per line |
| `BES_RAW_ROOT` | yes | `./BES_Raw` | Output root (sharded by 1000s) |
| `BATCH_START` | no | `0` | First index into shot list |
| `BATCH_END` | no | end of list | One past last index |
| `BES_WORKERS` | no | `8` | Ray worker count |
| `REQUIRE_FULL` | no | unset | If `1`, only skip shots with all 64 channels present |

## Idempotency

The pipeline skips shots that already have valid data in the output directory. To force a re-fetch, delete the per-shot HDF5 file:

```bash
rm /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/BES_Raw/146xxx/146077.h5
```

## Verify

Check that output files exist:

```bash
find /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/BES_Raw -name "*.h5" | wc -l
```

Inspect a single file:

```bash
h5dump -H /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/BES_Raw/146xxx/146077.h5
```

## Next

Continue to [06 - Interactive Debugging](06_INTERACTIVE_DEBUG.md).
