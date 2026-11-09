# Changelog

Timeline of major fixes and milestones for FDP on Polaris.

## 2026-11-08: Repo update (branch update-2026-11)

- New `toolkit/`: general signal fetcher (PTDATA + MDSplus, index-based absent/error, per-shot status JSON as the
  ledger), slice job, chain driver with lock/heartbeat, slice cutter, manifest, index reader, MDS node probe,
  installer, selftest. Site settings in `sites/site.env` (Polaris and Aurora templates).
- Docs rewritten (docs/01-07, AGENTS.md, TROUBLESHOOTING.md); June guides kept in docs/legacy/.
- `env/`: pinned pixi specs and locks of both FDP environments.
- ECEI/BES code updated to the versions that ran in production (index repoint, BES no_bes message).
- `examples/mirnov/`: the Mirnov campaign code.
- Tested on a Polaris compute node 2026-11-08: fdp_smoke and the index reader pass in both envs; old env toolkit
  fetch reproduces the Mirnov tier 1 store bit for bit (14/14 channels of 185000); CER IONS nodes verified
  (toolkit/signals/cer_quick_example.json). Fixed from the test: index pointnames are upper-case (ip was misread as
  absent); fdp-core has no h5py, so the toolkit env is env/fdp-2026-11 (fdp-core 1.30 + h5py, otherwise the same lock).

## 2026-10/11: Mirnov campaign (Polaris)

- Tier 1 (`MPI66M###D`, 52,143 shots): 52,130 stored, 1.98 TB, transferred to Aurora, sha256 verified.
- Job 2 (all other `MPI*D`): running, about 7 TB projected. Job 3 (`B1`-`B8`) prepared.
- Old env bit-identical to GA saga references (44/44 channels); float32 storage proven lossless per channel.
- Lane scaling measured (32/48/64 lanes); bad-worker failure mode identified; broken archive time bases found on 6 shots.
- Two debug queues fed by a login-node driver; capacity queue jobs waited 27+ h.

## 2026-10: BES + ECEI addendum; new tokens and proxy

- `fdp login` 24 h tokens (pelican device flow), `token_status.py`; stale-cookie login gotcha documented.
- ALCF proxy replaces the login-node proxy; verified for PTDATA, MDSplus, token checks.
- New env `fdp-2026-10` (fdp-core 1.30, ptdata 2.11.5) alongside the old env.
- Absent vs error classified from the pinned PTDATA index; the removed 2026-01-13 snapshot repointed.

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
