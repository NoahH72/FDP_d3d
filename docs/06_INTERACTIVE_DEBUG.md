# 06 - Interactive Debugging

## Goal

Debug the FDP pipeline interactively on a Polaris compute node.

## Prerequisites

- FDP installed and configured ([01 - Installation](01_INSTALLATION.md))
- Proxy running on the login node ([03 - Proxy Setup](03_PROXY_SETUP.md))
- Bearer token valid and stored at `~/.fdp/token`

## When to Use This

Use interactive mode before submitting large batch jobs, or when diagnosing failures. Interactive mode lets you run commands one at a time and inspect output immediately, making it far easier to isolate problems.

## Steps

### 1. Make sure the proxy is running on the login node

```bash
screen -ls | grep fdp_proxy
```

If no session is listed, start the proxy (see [03 - Proxy Setup](03_PROXY_SETUP.md)).

### 2. Request an interactive compute node

```bash
qsub -I -q debug \
  -l select=1:ncpus=4:mem=32gb,walltime=00:30:00,filesystems=eagle \
  -A <YOUR_PROJECT>
```

You will be dropped into a shell on a compute node (hostname like `x3001c0s1b0n0`).

### 3. Set up the environment

```bash
export ALL_PROXY=http://polaris-login-01:18443
export all_proxy=$ALL_PROXY
export CONDA_PREFIX=/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/.pixi/envs/default
export PREFIX="$CONDA_PREFIX"
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

**NOTE:** Replace `polaris-login-01` with the actual login node hostname where the proxy is running. Check with:

```bash
cat /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/.proxy_addr
```

### 4. Verify PTDATA connectivity (the core data access layer)

```bash
$CONDA_PREFIX/bin/fdp run python -m ptdata.check
```

Expected output: `All checks passed.` and `fetch ok: True`

### 5. Run a minimal 2-shot fetch

```bash
cd /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/ECEI-Data
BATCH_START=0 BATCH_END=2 \
  $CONDA_PREFIX/bin/fdp run $CONDA_PREFIX/bin/python FetchRawDataChannelWise.py --ray
```

### 6. Check a specific shot with the PTDATA check utility

```bash
PTDATA_CHECK_SHOT=142170 \
  $CONDA_PREFIX/bin/fdp run python \
  $PROJECT_ROOT/scripts/ptdata_check_shot.py
```

### 7. Test raw XRootD connectivity (lower level)

```bash
$CONDA_PREFIX/bin/python -c "
from pyxrootd.client import File
f = File()
url = 'pelican://osg-htc.org:443/fdp-d3d/archives/ptdata/165920/.EIL'
st, _ = f.open(url)
print('open ok:', st.ok)
f.close()
"
```

Expected output: `open ok: True`

### 8. When done, exit the compute node

```bash
exit
```

## Tips for Debugging

- **`ptdata.check` hangs for more than 30 seconds:** The proxy is probably down or `ALL_PROXY` is not set. Verify with `env | grep -i proxy`.
- **`fetch ok: False`:** Your bearer token is expired. Renew it (contact Brian at GA-FDP).
- **Verify proxy env vars are set:**
  ```bash
  env | grep -i proxy
  ```
- **Verify the pixi environment path:**
  ```bash
  env | grep CONDA_PREFIX
  ```
- **Segfault on the login node:** The login node PID limit of 128 means you cannot run full XRootD/ptdata on the login node itself (it will segfault). Always use a compute node or the `fdp_fetch_local.py` workaround.

## Verify

A successful run of `ptdata.check` (Step 4) confirms end-to-end connectivity: proxy, token, XRootD, and PTDATA are all working.

## Next

Continue to [07 - Monitoring and QA](07_MONITORING_AND_QA.md).
