# 04 - Running the ECEI Pipeline

## Goal

Fetch ECEI (Electron Cyclotron Emission Imaging) data from DIII-D and assemble it into HDF5 files on ALCF Polaris.

## Prerequisites

- FDP installed and configured ([01 - Installation](01_INSTALLATION.md))
- Proxy running on the login node ([03 - Proxy Setup](03_PROXY_SETUP.md))
- Bearer token valid and stored at `~/.fdp/token`

## Background

The ECEI pipeline uses TokSearch + Ray for parallel data extraction from the DIII-D archive.

**Channel layout:** 160 ECEI channels arranged as 20 rows x 8 columns, processed in 4 passes of 40 channels each.

**Pre-stage optimization:** The pipeline downloads the archive file once per shot, then extracts individual channels in parallel using `ThreadPoolExecutor`. This avoids redundant network transfers.

**Output format:** One HDF5 file per shot at the configured output directory.

```
HDF5 layout:
  2D/ecei/signal   shape: (T, 20, 8)   dtype: float32
  channel_means    shape: (20, 8)
  channel_stds     shape: (20, 8)
  freq             shape: (20, 8)
```

**Idempotency:** The pipeline skips shots that already have a valid `.h5` file in the output directory. To force a re-fetch, delete the existing file.

## Steps

### 1. Verify your bearer token is current

```bash
cat ~/.fdp/token | head -c 40   # should show JWT string
```

The token expires approximately 1 month from issue. Contact Brian (GA-FDP team) for renewal.

### 2. Verify the proxy is running

```bash
screen -ls | grep fdp_proxy   # should show a session
```

If no session is listed, start the proxy (see [03 - Proxy Setup](03_PROXY_SETUP.md)).

### 3. Set up your output and log directories

```bash
mkdir -p ~/pbs
# Output will go to the directory configured in pipeline/paths_config.py
# Default: /eagle/fusiondl_aesp/harrisn/signal_data/ECEI_Assembled/
```

### 4. Run a debug smoke test (2 shots, approximately 5 min)

```bash
cd $PROJECT_ROOT
qsub -A fusiondl_aesp \
  -q debug \
  -l select=1:ncpus=4:mem=32gb,walltime=01:00:00,filesystems=eagle \
  -v BATCH_START=0,BATCH_END=2 \
  pbs/run_batch_channelwise.pbs
```

### 5. Monitor the job

```bash
qstat -u $USER
tail -f ~/pbs/ecei_channelwise.out
```

Expected first lines of a healthy run:

```
Proxy reachable: https://osg-htc.org via http://polaris-login-XX:18443
Using FDP remote data access via fdp run wrapper
```

If you see `WARNING: proxy not reachable`, the proxy died. Restart it per [03 - Proxy Setup](03_PROXY_SETUP.md).

### 6. Submit a production batch (single node, preemptable queue)

```bash
qsub -A fusiondl_aesp \
  -v BATCH_START=0,BATCH_END=500 \
  pbs/run_batch_channelwise.pbs
```

The default PBS script requests 1 node, 32 CPUs, 200 GB RAM, 24 hr walltime on the preemptable queue.

### 7. Submit a multi-node production run (10 nodes, faster)

```bash
qsub -A fusiondl_aesp \
  -v BATCH_START=0,BATCH_END=1000 \
  pbs/run_batch_multinode.pbs
```

This divides the shot range across 10 nodes with staggered starts.

### 8. Submit a chained run (full 9890-shot dataset)

```bash
cd $PROJECT_ROOT
bash submit/submit_chain_pbs.sh
```

This submits N jobs as a PBS dependency chain (each handles `BATCH_SIZE` shots, default 500). To customize batch size:

```bash
BATCH_SIZE=250 bash submit/submit_chain_pbs.sh
```

## Key Environment Variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `BATCH_START` | `0` | First index into the shot list |
| `BATCH_END` | `10` | One past the last index |
| `RAY_MAX_WORKERS` | `16` | Number of Ray workers |
| `ROWS_PER_PASS` | `5` | ECEI rows per pass (affects memory: 5 rows ~ 5 GB/worker) |
| `OUTPUT_DIR` | (from paths_config) | Override output directory |
| `ECEI_PRESTAGE` | `1` | Enable pre-stage optimization (recommended) |

## Verify

Check that output files exist:

```bash
ls /eagle/fusiondl_aesp/harrisn/signal_data/ECEI_Assembled/*.h5 | wc -l
```

## Next

Continue to [05 - Running BES Pipeline](05_RUNNING_BES_PIPELINE.md).
