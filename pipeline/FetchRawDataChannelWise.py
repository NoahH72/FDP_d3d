"""
FetchRawDataChannelWise.py
--------------------------
Channel-wise ECEI pipeline using TokSearch, with grouped row-passes to
balance memory against connection/IO overhead.

Strategy: 4 passes of 5 rows (40 channels each) instead of 20 passes of
1 row (8 channels). This cuts PTDATA connection overhead and HDF5 open/
close cycles by 5x while keeping peak memory at ~5 GB/worker — well
within the 180 GB/24-CPU node budget.

- Pass 0 (rows 0-4):  Create HDF5, write rows 0-4. Atomic .tmp + os.replace.
- Passes 1-3:         Open existing HDF5, write that pass's 5 rows.
- Memory per worker:  ~40 channels (~5 GB) vs 160 (~15 GB full) or 8 (~1 GB).

Same output layout as FetchRawData: 2D/ecei/signal (T, 20, 8), channel_means,
channel_stds, freq. Same processing: truncate, downsample, spike removal.

Tuning: set ROWS_PER_PASS env var to adjust grouping. Default 5 (→ 4 passes).
  - ROWS_PER_PASS=1  → 20 passes, ~1 GB/worker (original behavior)
  - ROWS_PER_PASS=5  → 4 passes, ~5 GB/worker (default, recommended)
  - ROWS_PER_PASS=10 → 2 passes, ~10 GB/worker
  - ROWS_PER_PASS=20 → 1 pass, ~15 GB/worker (equivalent to FetchRawData)

Usage (on cluster):
    toksearch_submit -N 4 FetchRawDataChannelWise.py -- --ray

    Or for a specific batch range (set env vars before submitting):
    BATCH_START=0 BATCH_END=500 toksearch_submit -N 4 FetchRawDataChannelWise.py -- --ray

Module requirement:
    module load toksearch/release/python3.10/<latest>   # NOT 1.6.1
"""

import json
import os
import resource
import socket
import sys
import time
import traceback
from datetime import datetime, timezone

import h5py
import numpy as np
import toksearch as ts
if not hasattr(ts, 'PtDataSignal'):
    from toksearch_d3d import PtDataSignal
    ts.PtDataSignal = PtDataSignal

import ecei_io
import ecei_utils
import paths_config
import prestage
import resource_utils

# ---------------------------------------------------------------------------
# CONFIG  (override via environment variables; defaults from paths_config)
# ---------------------------------------------------------------------------
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", paths_config.ecei_assembled_dir)
CLEAN_SHOTS_FILE = os.environ.get("CLEAN_SHOTS_FILE", paths_config.clean_shots_file)
T_END_FILE = os.environ.get("T_END_FILE", paths_config.t_end_file)

D_SAMPLE = int(os.environ.get("D_SAMPLE", "1"))
RM_SPIKES = os.environ.get("RM_SPIKES", "1") == "1"
BATCH_START = int(os.environ.get("BATCH_START", "0"))
BATCH_END = int(os.environ.get("BATCH_END", "10"))
SHOT_BATCH_SIZE = 500

ROWS = 20   # vertical  (XX: 03-22)
COLS = 8    # horizontal (YY: 01-08)

# --- Grouping: 4 passes of 5 rows each (tunable) ---
ROWS_PER_PASS = int(os.environ.get("ROWS_PER_PASS", "5"))
NUM_PASSES = (ROWS + ROWS_PER_PASS - 1) // ROWS_PER_PASS  # ceil → 4

# HDF5 chunk cache — sized for one pass worth of data
HDF5_CHUNK_CACHE_NBYTES = int(2e9)


def ray_init_kwargs_for_fdp():
    """Arguments for ray.init so workers inherit Pelican proxy + FDP env (Polaris compute nodes).

    The PBS job sets ALL_PROXY on the driver; Ray workers do not always inherit the full
    environment, so we pass critical variables through runtime_env.env_vars.
    """
    kwargs = {}
    if os.environ.get("TMPDIR"):
        kwargs["_temp_dir"] = os.environ["TMPDIR"]

    env_vars = {}
    for k in (
        "ALL_PROXY",
        "all_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "NO_PROXY",
        "no_proxy",
        "BEARER_TOKEN",
        "CONDA_PREFIX",
        "PREFIX",
        "PTDATA_LOC",
        "PTDATA_JSON_INDEX_DIR",
        "PTDATA_PLUGIN_LIB",
        "PTDATA_LIBRARY",
        "XRD_PLUGINCONFDIR",
        "X509_CERT_FILE",
        "XRDCP_ALLOW_HTTP",
        "XRD_PELICANUSEAUTHHEADERS",
        "XRD_CURLDISABLEPREFETCH",
        "default_tree_path",
        "LD_LIBRARY_PATH",
        "SYS_D3",
        "SYS_D3_DELIM",
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
    ):
        v = os.environ.get(k)
        if v:
            env_vars[k] = v

    if env_vars:
        kwargs["runtime_env"] = {"env_vars": env_vars}
    kwargs.setdefault("logging_level", __import__("logging").ERROR)

    max_workers = int(os.environ.get("RAY_MAX_WORKERS", "8"))
    kwargs["num_cpus"] = max_workers

    return kwargs


def generate_channel_list():
    """Returns list of clean channel names: ['LFS0301', 'LFS0302', ..., 'LFS2208']"""
    return [f"LFS{xx:02d}{yy:02d}" for xx in range(3, 23) for yy in range(1, 9)]


CHANNELS = generate_channel_list()
CHANNELS_BY_ROW = [CHANNELS[i * COLS : (i + 1) * COLS] for i in range(ROWS)]


def get_pass_row_indices(pass_index):
    """Return list of row indices for this pass, e.g. pass 0 -> [0,1,2,3,4]."""
    start = pass_index * ROWS_PER_PASS
    end = min(start + ROWS_PER_PASS, ROWS)
    return list(range(start, end))


def get_pass_channels(pass_index):
    """Return flat list of channel names for all rows in this pass."""
    channels = []
    for row_idx in get_pass_row_indices(pass_index):
        channels.extend(CHANNELS_BY_ROW[row_idx])
    return channels


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def load_t_end_dict(t_end_file):
    if not t_end_file or not os.path.exists(t_end_file):
        return {}
    data = np.loadtxt(t_end_file)
    return {int(row[0]): float(row[1]) for row in data}


def chan_to_grid_idx(chan_name):
    """'LFS0301' -> (row=0, col=0)"""
    xx = int(chan_name[3:5])
    yy = int(chan_name[5:7])
    return xx - 3, yy - 1


def _drop_page_cache(file_path):
    """Tell kernel to evict this file's pages from the page cache.
    Prevents cache thrashing on BeeGFS when processing many large files."""
    try:
        fd = os.open(file_path, os.O_RDONLY)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        os.close(fd)
    except OSError:
        pass  # non-critical optimization


def _get_rss_mb():
    """Return current process RSS in MB. Uses /proc on Linux, else getrusage."""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    # Format: "VmRSS:    12345 kB"
                    return int(line.split()[1]) / 1024.0
    except (OSError, IndexError):
        pass
    try:
        # getrusage: ru_maxrss is in KB on Linux, bytes on some other systems
        r = resource.getrusage(resource.RUSAGE_SELF)
        val = r.ru_maxrss
        if val > 1e9:  # assume bytes if huge
            return val / (1024.0 * 1024.0)
        return val / 1024.0  # KB -> MB
    except Exception:
        return 0.0


def _get_peak_rss_mb():
    """Return peak RSS in MB. getrusage RUSAGE_SELF.ru_maxrss (KB on Linux)."""
    try:
        r = resource.getrusage(resource.RUSAGE_SELF)
        val = r.ru_maxrss
        if val > 1e9:
            return val / (1024.0 * 1024.0)
        return val / 1024.0
    except Exception:
        return 0.0


class ProfileCollector:
    """
    Records per-pass, per-batch timing and memory for scaling analysis.
    Controlled by ECEI_PROFILE=1. Zero-cost when disabled.
    """

    def __init__(self, enabled=False):
        self.enabled = enabled
        self.config = {}
        self.passes = []  # list of {"pass": int, "elapsed_s": float, "batches": [...]}
        self._pass_start = None
        self._pass_data = None
        self._batch_start = None
        self._run_start = None
        self._peak_rss_mb = 0.0

    def _sample_memory(self):
        if not self.enabled:
            return 0.0, 0.0
        rss = _get_rss_mb()
        peak = _get_peak_rss_mb()
        if peak > self._peak_rss_mb:
            self._peak_rss_mb = peak
        return rss, peak

    def set_config(self, num_cpus, memory_per_shot_gb, num_passes, shot_batch_size, total_shots):
        if not self.enabled:
            return
        self.config = {
            "num_cpus": num_cpus,
            "memory_per_shot_gb": memory_per_shot_gb,
            "num_passes": num_passes,
            "shot_batch_size": shot_batch_size,
            "total_shots": total_shots,
        }

    def start_run(self):
        if not self.enabled:
            return
        self._run_start = time.time()
        self._start_iso = datetime.now(timezone.utc).isoformat()
        self._peak_rss_mb = 0.0

    def start_pass(self, pass_index):
        if not self.enabled:
            return
        self._pass_start = time.time()
        self._pass_data = {"pass": pass_index, "elapsed_s": 0.0, "batches": []}

    def end_pass(self, pass_index):
        if not self.enabled:
            return
        if self._pass_start is not None:
            self._pass_data["elapsed_s"] = round(time.time() - self._pass_start, 2)
            self.passes.append(self._pass_data)
        self._pass_start = None
        self._pass_data = None

    def start_batch(self, pass_index, batch_num):
        if not self.enabled:
            return
        self._batch_start = time.time()
        rss_before, peak_before = self._sample_memory()
        self._batch_data = {
            "batch": batch_num,
            "shots": 0,
            "elapsed_s": 0.0,
            "s_per_shot": 0.0,
            "rss_mb_before": round(rss_before, 1),
            "rss_mb_after": 0.0,
            "peak_rss_mb": round(peak_before, 1),
        }

    def end_batch(self, pass_index, batch_num, n_shots):
        if not self.enabled:
            return
        elapsed = time.time() - self._batch_start
        rss_after, peak_after = self._sample_memory()
        if peak_after > self._peak_rss_mb:
            self._peak_rss_mb = peak_after
        self._batch_data["shots"] = n_shots
        self._batch_data["elapsed_s"] = round(elapsed, 2)
        self._batch_data["s_per_shot"] = round(elapsed / max(n_shots, 1), 2)
        self._batch_data["rss_mb_after"] = round(rss_after, 1)
        self._batch_data["peak_rss_mb"] = round(max(self._batch_data.get("peak_rss_mb", 0), peak_after), 1)
        if self._pass_data is not None:
            self._pass_data["batches"].append(self._batch_data)
        self._batch_start = None

    def end_run(self, n_shots):
        if not self.enabled:
            return
        self._run_elapsed = time.time() - self._run_start if self._run_start else 0.0
        self._end_iso = datetime.now(timezone.utc).isoformat()
        self._n_shots = n_shots

    def save(self, output_dir):
        if not self.enabled or not output_dir:
            return
        elapsed = getattr(self, "_run_elapsed", 0.0)
        n = getattr(self, "_n_shots", 0)
        s_per = elapsed / max(n, 1)
        report = {
            "job": {
                "pbs_jobid": os.environ.get("PBS_JOBID", ""),
                "slurm_jobid": os.environ.get("SLURM_JOB_ID", ""),
                "hostname": socket.gethostname(),
                "ncpus": os.environ.get("NCPUS", os.environ.get("SLURM_CPUS_ON_NODE", "")),
                "batch_start": os.environ.get("BATCH_START", ""),
                "batch_end": os.environ.get("BATCH_END", ""),
                "start_utc": getattr(self, "_start_iso", ""),
                "end_utc": getattr(self, "_end_iso", ""),
            },
            "config": self.config,
            "passes": self.passes,
            "total_elapsed_s": round(elapsed, 2),
            "s_per_shot": round(s_per, 2),
            "shots_per_hour": round(3600.0 / max(s_per, 0.01), 1),
            "peak_rss_mb": round(self._peak_rss_mb, 1),
            "extrapolation": {
                "1k_shots_1node_hr": round(1000 * s_per / 3600.0, 2),
                "5k_shots_1node_hr": round(5000 * s_per / 3600.0, 2),
                "9890_shots_1node_hr": round(9890 * s_per / 3600.0, 2),
                "9890_shots_4node_hr": round(9890 * s_per / 3600.0 / 4, 2),
            },
        }
        path = os.path.join(output_dir, "profiling_report.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Profiling report saved to {path}", flush=True)

    def print_summary(self):
        if not self.enabled:
            return
        if not hasattr(self, "_run_elapsed"):
            return
        n = getattr(self, "_n_shots", 0)
        s_per = self._run_elapsed / max(n, 1)
        sph = 3600.0 / max(s_per, 0.01)
        print("--- Profiling summary ---", flush=True)
        print(f"  Job:  {os.environ.get('PBS_JOBID', os.environ.get('SLURM_JOB_ID', 'N/A'))}"
              f"  Host: {socket.gethostname()}", flush=True)
        print(f"  Total: {self._run_elapsed:.1f}s for {n} shots "
              f"({s_per:.2f} s/shot, {sph:.0f} shots/hr)", flush=True)
        print(f"  Peak RSS: {self._peak_rss_mb:.1f} MB", flush=True)
        if self.passes:
            print("  Per-pass breakdown:", flush=True)
            for p in self.passes:
                ch = ROWS_PER_PASS * COLS
                r0 = p["pass"] * ROWS_PER_PASS
                r1 = min(r0 + ROWS_PER_PASS - 1, ROWS - 1)
                print(f"    Pass {p['pass']}: {p['elapsed_s']:.1f}s "
                      f"({ch} ch, rows {r0}-{r1})", flush=True)
        ext_9890 = 9890 * s_per / 3600.0
        print(f"  Extrapolation 9890 shots: {ext_9890:.1f} hr (1 node), "
              f"{ext_9890 / 4:.1f} hr (4 nodes)", flush=True)
        print("------------------------", flush=True)


def _process_one_channel_to_slice(raw_data, raw_time, t_limit_ms, fs_hz, dt_sec,
                                  d_sample, rm_spikes_flag, n_time,
                                  debug_chan=None):
    """Truncate, crop to [0, t_end], downsample, optionally spike-remove; return (proc_data, actual_len) or None."""
    if raw_data is None or raw_time is None or len(raw_data) < 2:
        return None
    if t_limit_ms is not None:
        mask = raw_time <= t_limit_ms
        raw_data = raw_data[mask]
        raw_time = raw_time[mask]
    # Crop to [0, t_end] (align with ECEI_local)
    mask = raw_time >= 0.0
    raw_data = raw_data[mask]
    raw_time = raw_time[mask]
    if len(raw_data) < 2:
        return None

    # One-off debug: log raw value at index 1223654 for LFS1204 (set ECEI_DEBUG_RAW=1)
    if debug_chan == "LFS1204" and os.environ.get("ECEI_DEBUG_RAW") == "1":
        idx = 1223654
        if len(raw_data) > idx:
            print(f"  [debug] {debug_chan} raw_data[{idx}] = {raw_data[idx]:.6f} (len={len(raw_data)})",
                  flush=True)

    proc_data, _ = ecei_utils.downsample_signal(raw_data, raw_time, fs_hz, d_sample)
    current_dt = dt_sec * d_sample

    if rm_spikes_flag:
        proc_data = np.asarray(proc_data, dtype=np.float64).copy()
        ecei_io.remove_spikes_custom_Z(
            proc_data,
            dt=current_dt,
            threshold=3,
            window=50,
            warmup_seconds=0.05,
        )
    else:
        proc_data = np.asarray(proc_data, dtype=np.float64)

    actual_len = min(len(proc_data), n_time)

    if len(proc_data) > n_time:
        print(f"  [debug] proc_data length {len(proc_data)} > n_time {n_time}, "
              f"truncating {len(proc_data) - n_time} samples (acquisition jitter?)",
              flush=True)

    return proc_data[:actual_len], actual_len


def _process_rows_into_dataset(rec, row_indices, dset, n_time, t_limit_ms,
                               fs_hz, dt_sec, d_sample, rm_spikes_flag):
    """
    Process and write multiple rows into an open HDF5 dataset.
    Returns (means_patch, stds_patch) shaped (len(row_indices), COLS).
    Shared by both pass-0 and pass-N workers to avoid duplicating the loop.
    """
    n_rows = len(row_indices)
    means_patch = np.zeros((n_rows, COLS), dtype=np.float64)
    stds_patch = np.zeros((n_rows, COLS), dtype=np.float64)

    for local_r, row_idx in enumerate(row_indices):
        channel_sum = np.zeros(COLS, dtype=np.float64)
        channel_sum_sq = np.zeros(COLS, dtype=np.float64)
        channel_count = np.zeros(COLS, dtype=np.float64)

        for col, chan in enumerate(CHANNELS_BY_ROW[row_idx]):
            sig = rec.get(chan, None)
            if sig is None:
                continue
            raw_data = sig.get("data")
            raw_time = sig.get("times")
            result = _process_one_channel_to_slice(
                raw_data, raw_time, t_limit_ms, fs_hz, dt_sec,
                d_sample, rm_spikes_flag, n_time,
                debug_chan=chan if (os.environ.get("ECEI_DEBUG_RAW") == "1" and rec["shot"] == 142095) else None,
            )
            if result is None:
                continue
            proc_data, actual_len = result
            dset[:actual_len, row_idx, col] = proc_data
            channel_sum[col] = np.sum(proc_data)
            channel_sum_sq[col] = np.sum(proc_data ** 2)
            channel_count[col] = float(actual_len)

        np.maximum(channel_count, 1.0, out=channel_count)
        row_means = channel_sum / channel_count
        row_vars = np.maximum(
            (channel_sum_sq / channel_count) - (row_means ** 2), 0.0,
        )
        means_patch[local_r, :] = row_means
        stds_patch[local_r, :] = np.sqrt(row_vars)

    return means_patch, stds_patch


# ---------------------------------------------------------------------------
# PASS 0 WORKER  (create HDF5, write first group of rows)
# ---------------------------------------------------------------------------
def process_pass0_shot(rec, pass_row_indices, t_end_dict, output_dir,
                       d_sample, rm_spikes_flag):
    """
    First pass: create full HDF5, write rows for pass 0 only.
    Atomic via .tmp + os.replace.
    """
    _timing = os.environ.get("ECEI_TIMING", "0") == "1"
    t0 = time.time() if _timing else None
    shot = rec["shot"]
    out_path = os.path.join(output_dir, f"{shot}.h5")
    tmp_path = out_path + ".tmp"

    try:
        if ecei_io.check_assembled_file(out_path):
            print(f"  [{shot}] pass0 skipped (already complete)", flush=True)
            return {"shot": shot, "status": "skipped"}

        t_limit_ms = None
        if t_end_dict and shot in t_end_dict:
            t_limit_ms = t_end_dict[shot] * 1000.0

        # Determine time axis from first valid channel across all rows in pass
        time_ms = None
        for row_idx in pass_row_indices:
            for chan in CHANNELS_BY_ROW[row_idx]:
                sig = rec.get(chan, None)
                if sig is None:
                    continue
                raw_time = sig.get("times")
                if raw_time is not None and len(raw_time) >= 2:
                    time_ms = raw_time
                    break
            if time_ms is not None:
                break

        if time_ms is None:
            print(f"  [{shot}] pass0 no_data", flush=True)
            return {"shot": shot, "status": "no_data"}

        if t_limit_ms is not None:
            mask = time_ms <= t_limit_ms
            if not np.any(mask):
                print(f"  [{shot}] pass0 truncated_empty", flush=True)
                return {"shot": shot, "status": "truncated_empty"}
            time_ms = time_ms[mask]
        # Crop to [0, t_end] (align with ECEI_local)
        mask = time_ms >= 0.0
        time_ms = time_ms[mask]
        if len(time_ms) < 2:
            print(f"  [{shot}] pass0 no_data", flush=True)
            return {"shot": shot, "status": "no_data"}

        dt_sec = float(time_ms[1] - time_ms[0]) / 1000.0
        fs_hz = 1.0 / dt_sec if dt_sec > 0 else 0.0
        _, time_ms_ds = ecei_utils.downsample_signal(time_ms, time_ms, fs_hz, d_sample)
        n_time = len(time_ms_ds)
        freq = int(round(fs_hz / d_sample)) if d_sample >= 1 else int(round(fs_hz))

        if _timing:
            t_setup = time.time() - t0
            print(f"  [{shot}] pass0 timing setup={t_setup:.3f}s", flush=True)

        os.makedirs(output_dir, exist_ok=True)

        with h5py.File(tmp_path, "w", rdcc_nbytes=HDF5_CHUNK_CACHE_NBYTES) as f:
            f.create_group("0D")
            f.create_group("1D")
            g2d = f.create_group("2D")
            g_ecei = g2d.create_group("ecei")

            f.create_dataset("t_disrupt", data=0.0)
            f.create_dataset("t_start", data=0.0)
            g_ecei.create_dataset("freq", data=freq)

            # Chunk shape (n, 1, 8): each row in its own chunks so later
            # passes don't read-modify-write (or decompress/recompress)
            # chunks belonging to other rows.
            dset = g_ecei.create_dataset(
                "signal",
                shape=(n_time, ROWS, COLS),
                dtype=np.float64,
                chunks=(min(n_time, 100_000), 1, COLS),
                compression="lzf",
            )

            means_patch, stds_patch = _process_rows_into_dataset(
                rec, pass_row_indices, dset, n_time, t_limit_ms,
                fs_hz, dt_sec, d_sample, rm_spikes_flag,
            )

            if _timing:
                t_process = time.time() - t0 - t_setup
                print(f"  [{shot}] pass0 timing process={t_process:.3f}s", flush=True)

            # Full (20, 8) means/stds; this pass's rows filled, rest zeros.
            channel_means = np.zeros((ROWS, COLS), dtype=np.float64)
            channel_stds = np.zeros((ROWS, COLS), dtype=np.float64)
            for local_r, row_idx in enumerate(pass_row_indices):
                channel_means[row_idx, :] = means_patch[local_r, :]
                channel_stds[row_idx, :] = stds_patch[local_r, :]
            g_ecei.create_dataset("channel_means", data=channel_means)
            g_ecei.create_dataset("channel_stds", data=channel_stds)

        os.replace(tmp_path, out_path)
        _drop_page_cache(out_path)

        if _timing:
            t_total = time.time() - t0
            print(f"  [{shot}] pass0 timing total={t_total:.3f}s", flush=True)
        print(f"  [{shot}] pass0 ok  (rows {pass_row_indices[0]}-{pass_row_indices[-1]})",
              flush=True)
        return {"shot": shot, "status": "ok", "n_time": n_time}

    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        print(f"  [{shot}] pass0 error", flush=True)
        print(traceback.format_exc(), flush=True)
        return {"shot": shot, "status": f"error: {traceback.format_exc()}"}


# ---------------------------------------------------------------------------
# PASS N WORKER  (open existing HDF5, write one group of rows)
# ---------------------------------------------------------------------------
def process_passN_shot(rec, pass_index, pass_row_indices, t_end_dict,
                       output_dir, d_sample, rm_spikes_flag):
    """
    Passes 1..N-1: open existing HDF5, write signal and stats for this
    pass's group of rows.
    """
    _timing = os.environ.get("ECEI_TIMING", "0") == "1"
    t0 = time.time() if _timing else None
    shot = rec["shot"]
    out_path = os.path.join(output_dir, f"{shot}.h5")

    try:
        # Wait for pass-0's file to appear (filesystem propagation delay)
        for attempt in range(3):
            if os.path.exists(out_path):
                break
            time.sleep(5)
        else:
            print(f"  WARNING [{shot}] pass{pass_index} skipped_no_file: "
                  f"{out_path} not found after 3 retries (15s). "
                  f"This shot will be INCOMPLETE (rows {pass_row_indices[0]}-"
                  f"{pass_row_indices[-1]} missing).", flush=True)
            return {"shot": shot, "status": "skipped_no_file", "pass": pass_index}

        t_limit_ms = None
        if t_end_dict and shot in t_end_dict:
            t_limit_ms = t_end_dict[shot] * 1000.0

        # Get dt/fs from first valid channel in this pass's rows
        dt_sec = None
        fs_hz = None
        for row_idx in pass_row_indices:
            for chan in CHANNELS_BY_ROW[row_idx]:
                sig = rec.get(chan, None)
                if sig is None:
                    continue
                raw_time = sig.get("times")
                if raw_time is not None and len(raw_time) >= 2:
                    dt_sec = float(raw_time[1] - raw_time[0]) / 1000.0
                    fs_hz = 1.0 / dt_sec if dt_sec > 0 else 0.0
                    break
            if dt_sec is not None:
                break

        if dt_sec is None or fs_hz is None:
            print(f"  [{shot}] pass{pass_index} no_data", flush=True)
            return {"shot": shot, "status": "no_data", "pass": pass_index}

        if _timing:
            t_setup = time.time() - t0
            print(f"  [{shot}] pass{pass_index} timing setup={t_setup:.3f}s", flush=True)

        with h5py.File(out_path, "r+", rdcc_nbytes=HDF5_CHUNK_CACHE_NBYTES) as f:
            g_ecei = f["2D"]["ecei"]
            dset = g_ecei["signal"]
            n_time = dset.shape[0]

            means_patch, stds_patch = _process_rows_into_dataset(
                rec, pass_row_indices, dset, n_time, t_limit_ms,
                fs_hz, dt_sec, d_sample, rm_spikes_flag,
            )

            if _timing:
                t_process = time.time() - t0 - t_setup
                print(f"  [{shot}] pass{pass_index} timing process={t_process:.3f}s",
                      flush=True)

            for local_r, row_idx in enumerate(pass_row_indices):
                g_ecei["channel_means"][row_idx, :] = means_patch[local_r, :]
                g_ecei["channel_stds"][row_idx, :] = stds_patch[local_r, :]

        _drop_page_cache(out_path)
        if _timing:
            t_total = time.time() - t0
            print(f"  [{shot}] pass{pass_index} timing total={t_total:.3f}s", flush=True)
        print(f"  [{shot}] pass{pass_index} ok  (rows {pass_row_indices[0]}-{pass_row_indices[-1]})",
              flush=True)
        return {"shot": shot, "status": "ok", "pass": pass_index}

    except Exception:
        print(f"  [{shot}] pass{pass_index} error", flush=True)
        print(traceback.format_exc(), flush=True)
        return {"shot": shot, "status": f"error: {traceback.format_exc()}",
                "pass": pass_index}


# ---------------------------------------------------------------------------
# POST-LOOP VALIDATION
# ---------------------------------------------------------------------------
def validate_outputs(shots_to_do, output_dir):
    """
    After all passes, verify each shot's HDF5 is complete.
    Checks:
      1. ecei_io.check_assembled_file passes
      2. No row of channel_means is all-zero (indicates a missing pass)
    Returns list of incomplete/missing shot numbers.
    """
    ok_count = 0
    incomplete = []
    missing = []

    for shot in shots_to_do:
        out_path = os.path.join(output_dir, f"{shot}.h5")

        if not os.path.exists(out_path):
            missing.append(shot)
            continue

        if not ecei_io.check_assembled_file(out_path):
            incomplete.append((shot, "failed check_assembled_file"))
            continue

        try:
            with h5py.File(out_path, "r") as f:
                means = f["2D"]["ecei"]["channel_means"][:]
                zero_rows = [r for r in range(ROWS) if np.all(means[r, :] == 0.0)]
                if zero_rows:
                    incomplete.append(
                        (shot, f"all-zero channel_means in rows {zero_rows}")
                    )
                else:
                    ok_count += 1
        except Exception as e:
            incomplete.append((shot, f"validation error: {e}"))

    total = len(shots_to_do)
    n_incomplete = len(incomplete)
    n_missing = len(missing)
    print(f"\n--- Post-loop validation ---")
    print(f"  {ok_count}/{total} shots OK")
    if n_missing:
        print(f"  {n_missing} shots MISSING (no HDF5 file):")
        for s in missing[:20]:
            print(f"    shot {s}")
        if n_missing > 20:
            print(f"    ... and {n_missing - 20} more")
    if n_incomplete:
        print(f"  {n_incomplete} shots INCOMPLETE:")
        for s, reason in incomplete[:20]:
            print(f"    shot {s}: {reason}")
        if n_incomplete > 20:
            print(f"    ... and {n_incomplete - 20} more")
    print(f"----------------------------\n")

    return [s for s in missing] + [s for s, _ in incomplete]


# ---------------------------------------------------------------------------
# DRIVER  — run NUM_PASSES grouped passes, each with shot batches
# ---------------------------------------------------------------------------
def run_fetch_raw_channelwise_job(
    shot_list,
    output_dir=None,
    t_end_file=None,
    d_sample=None,
    rm_spikes=None,
):
    """
    Run the grouped channel-wise pipeline: NUM_PASSES passes (default 4),
    each fetching ROWS_PER_PASS rows (default 5, 40 channels) per shot.
    """
    output_dir = output_dir or OUTPUT_DIR
    t_end_file = t_end_file or T_END_FILE
    d_sample = d_sample if d_sample is not None else D_SAMPLE
    rm_spikes = rm_spikes if rm_spikes is not None else RM_SPIKES

    os.makedirs(output_dir, exist_ok=True)
    t_end_dict = load_t_end_dict(t_end_file)

    # Pre-filter: only shots without a valid assembled file
    shots_to_do = []
    for s in shot_list:
        out_path = os.path.join(output_dir, f"{s}.h5")
        if not ecei_io.check_assembled_file(out_path):
            shots_to_do.append(s)
    if not shots_to_do:
        print("All shots already have valid assembled files. Nothing to do.")
        return 0.0
    print(f"Shots to process: {len(shots_to_do)} "
          f"(skipped {len(shot_list) - len(shots_to_do)} already done)")
    print(f"Pass structure: {NUM_PASSES} passes x {ROWS_PER_PASS} rows "
          f"= {ROWS_PER_PASS * COLS} channels/pass")

    use_ray = "--ray" in sys.argv
    use_prestage = "--prestage" in sys.argv or os.environ.get("ECEI_PRESTAGE") == "1"
    num_cpus = resource_utils.get_allowed_cpus()

    # Memory budget: 40 channels x ~4M samples x 8 bytes = ~1.3 GB raw.
    # With processing copies (filter, spike removal) ~2-3x overhead -> ~4 GB.
    # 5 GB gives headroom. On a 180 GB node this allows ~36 workers,
    # more than the 24 CPUs available, so we're CPU-bound not memory-bound.
    memory_per_shot = int(5e9)

    profile = ProfileCollector(enabled=os.environ.get("ECEI_PROFILE") == "1")
    profile.set_config(
        num_cpus=num_cpus,
        memory_per_shot_gb=memory_per_shot / 1e9,
        num_passes=NUM_PASSES,
        shot_batch_size=SHOT_BATCH_SIZE,
        total_shots=len(shots_to_do),
    )
    profile.start_run()

    t0 = time.time()

    stager = None
    if use_prestage:
        stager = prestage.ShotPreStager(
            channels=CHANNELS,
            max_concurrent=int(os.environ.get("PRESTAGE_CONCURRENCY", "8")),
        )
        print(f"Pre-stage enabled: cache={stager.cache_dir}, "
              f"concurrency={stager.max_concurrent}", flush=True)

    for pass_index in range(NUM_PASSES):
        pass_row_indices = get_pass_row_indices(pass_index)
        pass_channels = get_pass_channels(pass_index)
        num_batches = (len(shots_to_do) + SHOT_BATCH_SIZE - 1) // SHOT_BATCH_SIZE

        profile.start_pass(pass_index)

        for batch_start in range(0, len(shots_to_do), SHOT_BATCH_SIZE):
            batch = shots_to_do[batch_start : batch_start + SHOT_BATCH_SIZE]
            batch_num = batch_start // SHOT_BATCH_SIZE + 1
            print(f"Pass {pass_index + 1}/{NUM_PASSES} "
                  f"(rows {pass_row_indices[0]}-{pass_row_indices[-1]})  "
                  f"Batch {batch_num}/{num_batches}  ({len(batch)} shots)",
                  flush=True)

            profile.start_batch(pass_index, batch_num)

            saved_env = {}
            if stager is not None:
                t_ps = time.time()
                stager.prestage_shots(batch)
                print(f"  [prestage] pass {pass_index} batch {batch_num}: "
                      f"{time.time() - t_ps:.1f}s", flush=True)
                overrides = stager.get_env_overrides()
                for k, v in overrides.items():
                    saved_env[k] = os.environ.get(k)
                    os.environ[k] = v
                for k in ("PTDATA_JSON_INDEX_DIR", "PTDATA_PLUGIN_LIB"):
                    saved_env[k] = os.environ.pop(k, None)

            try:
                pipe = ts.Pipeline(batch)

                if stager is not None:
                    _chans = pass_channels
                    _stg = stager
                    _n_threads = int(os.environ.get("PRESTAGE_FETCH_THREADS", "8"))

                    @pipe.map
                    def parallel_local_fetch(rec, _c=_chans, _s=_stg, _nt=_n_threads):
                        ch_data = prestage.parallel_fetch_channels(
                            rec["shot"], _c, _s, max_threads=_nt,
                        )
                        for ch, data in ch_data.items():
                            rec[ch] = data
                        return rec
                else:
                    for chan in pass_channels:
                        pipe.fetch(chan, ts.PtDataSignal(chan))

                p_idx = pass_index
                p_rows = pass_row_indices

                if p_idx == 0:

                    @pipe.map
                    def process_shot_pass0(rec, _rows=p_rows):
                        return process_pass0_shot(
                            rec,
                            pass_row_indices=_rows,
                            t_end_dict=t_end_dict,
                            output_dir=output_dir,
                            d_sample=d_sample,
                            rm_spikes_flag=rm_spikes,
                        )
                else:

                    @pipe.map
                    def process_shot_passN(rec, _p=p_idx, _rows=p_rows):
                        return process_passN_shot(
                            rec,
                            pass_index=_p,
                            pass_row_indices=_rows,
                            t_end_dict=t_end_dict,
                            output_dir=output_dir,
                            d_sample=d_sample,
                            rm_spikes_flag=rm_spikes,
                        )

                pipe.keep([])

                if use_ray:
                    ray_kwargs = ray_init_kwargs_for_fdp()
                    if stager is not None:
                        env_update = ray_kwargs.get("runtime_env", {}).get("env_vars", {})
                        env_update["PTDATA_LOC"] = "0"
                        env_update["SYS_D3"] = str(stager.cache_dir)
                        env_update.pop("PTDATA_JSON_INDEX_DIR", None)
                        env_update.pop("PTDATA_PLUGIN_LIB", None)
                    pipe.compute_ray(
                        memory_per_shot=memory_per_shot,
                        ray_init_kwargs=ray_kwargs,
                    )
                    import ray as _ray
                    _ray.shutdown()
                else:
                    pipe.compute_serial()

            finally:
                for k, v in saved_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            profile.end_batch(pass_index, batch_num, len(batch))

        profile.end_pass(pass_index)

    elapsed = time.time() - t0
    n = len(shots_to_do)
    print(f"Done. {n} shots ({NUM_PASSES} passes) in {elapsed:.1f}s  "
          f"({elapsed / max(n, 1):.1f} s/shot)")

    profile.end_run(n_shots=n)
    profile.save(output_dir)
    profile.print_summary()

    bad_shots = validate_outputs(shots_to_do, output_dir)
    if bad_shots:
        print(f"WARNING: {len(bad_shots)} shots may need re-processing.")

    return elapsed


def main():
    shots_all = paths_config.load_clean_shot_list(CLEAN_SHOTS_FILE)
    shots = shots_all[BATCH_START:BATCH_END]
    print(f"Shots: {len(shots)} (indices {BATCH_START}:{BATCH_END})")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Channels: {len(CHANNELS)} total, {ROWS_PER_PASS} rows/pass "
          f"({ROWS_PER_PASS * COLS} ch/pass), D_SAMPLE={D_SAMPLE}, RM_SPIKES={RM_SPIKES}")
    print(f"Shot batch size: {SHOT_BATCH_SIZE}")

    run_fetch_raw_channelwise_job(
        shots.tolist(),
        output_dir=OUTPUT_DIR,
        t_end_file=T_END_FILE,
        d_sample=D_SAMPLE,
        rm_spikes=RM_SPIKES,
    )


if __name__ == "__main__":
    main()