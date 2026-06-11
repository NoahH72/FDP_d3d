# Issues and Future Work

## Known Issues

### 1. Login Node PID Limit (128)

- The Polaris login node cgroup limits PIDs (processes + threads) to 128. Cursor's Node.js processes consume ~95, leaving only ~25 for Python + XRootD. XRootD's `XrdPosix` layer needs ~20+ threads (Poller, TaskMgr, JobMgr, curl workers), exceeding the budget and causing `EAGAIN` / segfault.
- **Impact:** Cannot run full ptdata remote fetch directly on the login node (only on compute nodes).
- **Workaround:** Always use compute nodes (via PBS jobs or interactive `qsub -I`). Alternatively, use the `fdp_fetch_local.py` script which pre-downloads via `pyxrootd` (which uses `XrdCl` directly, fewer threads) and then runs ptdata in local mode.
- **Possible fix:** Ask ALCF to raise `pids.max` from 128 to 256, or run from a plain SSH terminal without Cursor/VS Code.

### 2. Bearer Token Expiration

- FDP bearer tokens are valid for ~1 month from issue date.
- **Impact:** Jobs fail with `fetch ok: False` after token expiry.
- **Workaround:** Track expiry date. Contact Brian (GA-FDP team) or use the [token request form](https://forms.office.com/g/wEaBDGqqq8) for renewal. Place new token at `~/.fdp/token`.
- **Possible fix:** Implement token auto-renewal or longer-lived tokens.

### 3. channel_means Validation Warning

- The post-processing validation step may report `all-zero channel_means rows 5-19` for certain older shots.
- **Impact:** Cosmetic warning only — data is usually valid. This occurs when older shots have fewer ECEI channels populated.
- **Workaround:** Inspect the HDF5 file manually to confirm data integrity.

### 4. Proxy Persistence

- The HTTPS proxy runs in a `screen` session on a login node. It survives SSH disconnects but does NOT survive login node reboots.
- **Impact:** All compute node jobs will fail if the proxy goes down.
- **Workaround:** Check proxy status before submitting jobs (`screen -ls | grep fdp_proxy`). Restart if needed.
- **Possible fix:** Run proxy as a systemd user service, or implement automatic proxy health checks in PBS scripts with restart capability.

## Resolved Issues

### XRootD Plugin Symlinks (Fixed 2026-04-07)

- `pelican-plugin.conf` referenced unversioned library names (`libXrdClPelican.so`) but only versioned files (`libXrdClPelican-5.so`) were shipped.
- **Fix:** Created symlinks: `ln -sf libXrdClPelican-5.so libXrdClPelican.so` (and similarly for Curl and S3 plugins).

### Compute Node Network Access (Fixed 2026-04-07)

- Polaris compute nodes have no outbound internet, blocking FDP/Pelican fetches.
- **Fix:** HTTP CONNECT proxy on login node, accessed via `ALL_PROXY` env var. See [03 - Proxy Setup](docs/03_PROXY_SETUP.md).

### ALL_PROXY vs https_proxy (Fixed 2026-04-07)

- XRootD's libcurl plugin respects `ALL_PROXY` but NOT `https_proxy` alone.
- **Fix:** Set both `ALL_PROXY` and `all_proxy` env vars in PBS scripts.

### Ray API Mismatch (Fixed 2026-04-12)

- `compute_ray()` was called with an unsupported `num_cpus` argument in newer TokSearch.
- **Fix:** Removed the `num_cpus` argument.

### Ray Temp Directory Path Length (Fixed 2026-04-12)

- PBS job temp paths are too long for Ray's AF_UNIX socket limit (107 bytes), causing Ray startup to fail.
- **Fix:** Set `TMPDIR=/tmp/ray_<JOBID>` in PBS scripts.

### Ray Worker Env Propagation (Fixed 2026-04-12)

- Ray workers did not inherit proxy and token env vars, causing data fetches to fail on workers.
- **Fix:** `ray_init_kwargs_for_fdp()` in `resource_utils.py` now passes `runtime_env.env_vars` with `ALL_PROXY`, `BEARER_TOKEN`, etc.

### PtDataSignal Import (Fixed 2026-04-07)

- FDP pixi env moved `PtDataSignal` from `toksearch` to `toksearch_d3d`.
- **Fix:** Backward-compatible import: `if not hasattr(ts, 'PtDataSignal'): from toksearch_d3d import PtDataSignal`.

## Future Work

### Production Scale

- [ ] Complete full 9890-shot ECEI dataset fetch
- [ ] Validate all output HDF5 files (channel_means, signal shapes)
- [ ] Scale to 20+ nodes for faster completion (~2.5 hr at 20 nodes)

### Performance

- [ ] Test 24-32 Ray workers per node (64 CPU cores available, only 16 currently used)
- [ ] Investigate Pelican CDN caching — repeated downloads of the same shots should be faster
- [ ] Consider pre-downloading the full dataset to Eagle filesystem for repeated experiments (eliminates CDN latency)
- [ ] Profile memory usage at higher worker counts

### Infrastructure

- [ ] Implement bearer token auto-renewal or monitoring
- [ ] Convert proxy from `screen` session to a more robust daemon (systemd user service or similar)
- [ ] Add automatic proxy health check + restart in PBS job scripts
- [ ] Investigate `toksearch_submit` integration for distributed runs (Polaris SLURM config template exists but is untested)

### Code Quality

- [ ] Add unit tests for ecei_io, ecei_utils, prestage modules
- [ ] Add CI/CD pipeline for linting and testing
- [ ] Package pipeline code as an installable Python package
- [ ] Consolidate paths_config.py defaults so users don't need to edit source code
