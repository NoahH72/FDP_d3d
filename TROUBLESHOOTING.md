# Troubleshooting

Quick reference for common issues. For detailed guides, see the [docs/](docs/) folder.

## Connection and Proxy Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `WARNING: proxy not reachable` in PBS log | The `screen fdp_proxy` session died or login node rebooted | Restart proxy: `screen -dmS fdp_proxy python3 scripts/https_proxy.py --port 18443` |
| `fdp run python -m ptdata.check` hangs >30s | `ALL_PROXY` not set, or proxy is down | Verify proxy is running (`screen -ls`); check env vars (`echo $ALL_PROXY`) |
| `curl: connection refused` from compute node | Compute node has no direct internet | Set `ALL_PROXY` and `all_proxy` to point to the login node proxy |
| Proxy starts but compute node can't reach it | Wrong login node hostname in proxy address | Check `cat /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/.proxy_addr`; restart proxy if on wrong node |

## Authentication Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `fetch ok: False` in ptdata.check | Bearer token expired | Renew token from Brian (GA-FDP); place at `~/.fdp/token` |
| `~/.fdp/token` is empty or missing | Token never set up | See [Prerequisites](docs/01_PREREQUISITES.md) for token setup |
| `WARNING: BEARER_TOKEN not found` | Token file missing or wrong path | Verify `cat ~/.fdp/token` shows a JWT string starting with `eyJ` |

## PBS / Job Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `Batch: BATCH_START=0 BATCH_END=10` (default values) | Forgot `-v BATCH_START=...,BATCH_END=...` | Resubmit with correct `-v` args |
| `qsub: Job rejected: Unknown queue` | Wrong queue name | Use `debug` (short jobs) or `preemptable` (production) |
| Job output appears in wrong directory | PBS log path issue | Create `~/pbs/` directory: `mkdir -p ~/pbs` |
| Job fails immediately with exit code 1 | Proxy not reachable (pre-flight check fails) | Start the proxy before submitting |

## Environment Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'toksearch'` | Wrong Python binary or env not installed | Run `install_fdp_polaris.sh`; verify `$CONDA_PREFIX/bin/python -c "import toksearch"` |
| `Segmentation fault` on login node | Login node PID limit (128) exceeded by XRootD threads | Use compute node instead; or reduce Cursor/VS Code processes |
| `EAGAIN` or `Resource temporarily unavailable` during `pixi install` | Login node PID limit | Run `pixi install` on an interactive compute node |
| `Permission denied` for SSH compute to login | `authorized_keys` missing or wrong permissions | Run: `cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys` |

## Ray Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `AF_UNIX path too long` or Ray startup fails | PBS temp directory path exceeds 107 byte limit | Set `TMPDIR=/tmp/ray_$PBS_JOBID` (already done in PBS scripts) |
| Ray workers fail to fetch data | Proxy/token env vars not propagated to workers | Ensure `resource_utils.ray_init_kwargs_for_fdp()` is used (already wired in) |
| `TypeError: compute_ray() got unexpected keyword argument 'num_cpus'` | Newer TokSearch API change | Remove `num_cpus` arg from `compute_ray()` call |

## Data Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `all-zero channel_means rows 5-19` warning | Older shot with fewer ECEI channels | Inspect HDF5 manually; usually valid data |
| Missing shots in output | Shot has no ECEI data on CDN, or job was preempted | Check CDN availability; resubmit (pipeline skips existing files) |
| Output HDF5 file is 0 bytes or corrupt | Job was killed during write | Delete the file and resubmit; pipeline uses atomic `.tmp` + `os.replace` |

## Quick Diagnostic Commands

```bash
# Check proxy status
screen -ls | grep fdp_proxy
curl -s --max-time 5 --proxy "http://$(cat /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/.proxy_addr)" \
  https://osg-htc.org -o /dev/null && echo "proxy OK" || echo "proxy DEAD"

# Check token
cat ~/.fdp/token | head -c 40

# Check token expiry
cat ~/.fdp/token | cut -d'.' -f2 | base64 -d 2>/dev/null | python3 -c \
  "import sys,json,datetime; d=json.load(sys.stdin); \
   print('exp:', datetime.datetime.fromtimestamp(d['exp']), '| now:', datetime.datetime.now())"

# Check FDP environment
ls /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/.pixi/envs/default/bin/python
/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/.pixi/envs/default/bin/python -c "import toksearch; print('OK')"

# Check all jobs
qstat -u $USER

# Check output count
ls /eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/signal_data/ECEI_Assembled/*.h5 2>/dev/null | wc -l
```
