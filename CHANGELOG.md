# Changelog

Timeline of major fixes and milestones for FDP on Polaris.

## 2026-04-13 — Performance Optimization

- Implemented parallel pre-stage optimization achieving 6.5x speedup (137 s/shot to 21 s/shot)
- Benchmarked full pipeline: network (745 Mbps, not bottleneck), ptdata64 extraction (5 s/channel, real bottleneck)
- Tested 8-worker (21.1 s/shot) and 16-worker (18.6 s/shot) configurations
- Published performance report with scaling projections

## 2026-04-12 — End-to-End PBS Validation

- Successfully processed shots 142095 (263 MB HDF5) and 142170 (865 MB HDF5) to `ECEI_Assembled_SmokeTest/`
- Fixed Ray API mismatch: removed unsupported `num_cpus` arg from `compute_ray()`
- Fixed Ray temp dir: set `TMPDIR=/tmp/ray_<JOBID>` in PBS script to avoid AF_UNIX path length limit
- Fixed Ray worker env propagation: `ray_init_kwargs_for_fdp()` now passes `runtime_env.env_vars` with `ALL_PROXY`, `BEARER_TOKEN`, etc.

## 2026-04-07 — Compute Node Solution

- Deployed HTTP CONNECT proxy (`https_proxy.py`) on login node for compute node internet access
- Confirmed: `pyxrootd.client.File().open()` works through proxy (`ok: True`)
- Confirmed: `fdp run python -m ptdata.check` works on compute node through proxy (`fetch ok: True`)
- Successfully fetched signal IP, shot 165920 on compute node `x3001c0s1b0n0`
- Wired proxy (`ALL_PROXY`) into `run_batch_channelwise.pbs` with automatic address discovery from `.proxy_addr`
- Discovered: XRootD respects `ALL_PROXY` but NOT `https_proxy` alone; both `ALL_PROXY` and `all_proxy` must be set

## 2026-04-07 — Import and Plugin Fixes

- Fixed XRootD plugin symlinks: created `libXrdClPelican.so`, `libXrdClCurl.so`, `libXrdClS3.so` pointing to versioned `-5.so` files
- Fixed pipeline imports: added backward-compatible `from toksearch_d3d import PtDataSignal` fallback in `FetchRawDataChannelWise.py` and `FetchRawData.py`
- Updated PBS scripts to use `fdp run` wrapper when `USE_FDP=1`

## 2026-04-06 — Bearer Token Setup

- Obtained first FDP bearer token (1-month validity)
- Placed at `~/.fdp/token`; verified ptdata reads it via `BEARER_TOKEN` env var

## 2026-03-31 — Initial FDP Install

- Installed FDP pixi environment on Eagle filesystem
- Resolved `pixi install` failure on login node (cgroup PID limit) — must run on compute node
- Verified all libraries load: `libd3.so`, `ptdata_ext`, `libjson_index_plugin.so`, XRootD plugins
- Verified SSL certs and XRootD plugin config directories exist
- Resolved OpenBLAS thread crash with `OPENBLAS_NUM_THREADS=1`
