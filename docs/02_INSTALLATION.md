# 02 - Installation

## Goal

Install the FDP pixi environment on Polaris so you can fetch and process DIII-D diagnostic data.

---

## Prerequisites

Complete [01 - Prerequisites](01_PREREQUISITES.md) before continuing.

---

## Background

FDP uses [pixi](https://pixi.sh/) (a conda-compatible package manager) to create a reproducible Python 3.11 environment containing `toksearch_d3d`, `ptdata`, XRootD Pelican plugins, and all dependencies. The environment is installed once to the Eagle filesystem and shared across PBS jobs.

The key package is **`toksearch_d3d`** (from the `ga-fdp` conda channel), which ships `ptdata`, `toksearch`, `toksearch_d3d`, the `fdp` CLI, and XRootD Pelican plugins.

The `pixi.toml` in `env/` shows the full dependency list: Python 3.11, `toksearch_d3d >=0.4.0`, `numba`, `h5py`, `ga-dfl-labeler`, and more.

> **IMPORTANT:** `pixi install` can fail on login nodes due to a cgroup PID limit of 128. You **MUST** run the installation on an interactive compute node.

---

## Steps

### 1. SSH to a Polaris login node

```bash
ssh <username>@polaris.alcf.anl.gov
```

### 2. Clone this repo (or navigate to it if already cloned)

```bash
git clone https://github.com/NoahH72/FDP_d3d.git
cd FDP_d3d
```

### 3. Get an interactive compute node

```bash
qsub -I -q debug -l select=1:ncpus=4:mem=32gb,walltime=01:00:00,filesystems=eagle -A fusiondl_aesp
```

Wait for the job to start. You will be dropped into a shell on a compute node.

### 4. Run the installer

```bash
bash scripts/install_fdp_polaris.sh
```

This script does the following:

1. Creates a `fdp-installer` conda environment (from the `ga-fdp` channel)
2. Runs `fdp-install` to generate a pixi project with `pixi.toml`
3. Runs `pixi install` to resolve and install all packages
4. Smoke-tests the installation (`import toksearch`, `import numba`, `import h5py`)

Expected final output:

```
FDP env OK
```

The install takes several minutes. The installed environment lives at `$FDP_DIR/.pixi/envs/default/`, where `$FDP_DIR` is the directory where the FDP pixi project was installed (default: `/eagle/fusiondl_aesp/harrisn/fdp`).

### 5. Fix XRootD plugin symlinks (one-time, required)

The XRootD plugin config files reference unversioned library names, but only the versioned `-5.so` files are shipped. Create the missing symlinks:

```bash
cd /eagle/fusiondl_aesp/harrisn/fdp/.pixi/envs/default/lib
ln -sf libXrdClPelican-5.so libXrdClPelican.so
ln -sf libXrdClCurl-5.so    libXrdClCurl.so
ln -sf libXrdClS3-5.so      libXrdClS3.so
```

If your `$FDP_DIR` is different from the default `/eagle/fusiondl_aesp/harrisn/fdp`, adjust the path accordingly.

### 6. Exit the compute node

```bash
exit
```

You will be returned to the login node.

---

## Verify

From a login node, confirm the environment works:

```bash
export CONDA_PREFIX=/eagle/fusiondl_aesp/harrisn/fdp/.pixi/envs/default
export PREFIX="$CONDA_PREFIX"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
$CONDA_PREFIX/bin/python -c "import toksearch; print('OK')"
```

Expected output:

```
OK
```

If you see import errors, re-run step 4 on a compute node and check the script output for failures.

---

## Next

Continue to [03 - Proxy Setup](03_PROXY_SETUP.md).
