"""
FetchRawData.py
---------------
Single-pass ECEI pipeline using TokSearch + toksearch_submit.

Each shot is processed by one Ray worker:
  1. Fetch all 160 ECEI channels from MDS/PTDATA
  2. Process (downsample, spike removal) and write each channel directly to HDF5
  3. Output: assembled/{shot}.h5  shape=(Time, 20, 8), float64, lzf compression

No intermediate per-channel files. No separate assembly step.

Usage (on cluster):
    toksearch_submit -N 4 FetchRawData.py -- --ray

    Or for a specific batch range (set env vars before submitting):
    BATCH_START=0 BATCH_END=500 toksearch_submit -N 4 FetchRawData.py -- --ray

Module requirement:
    module load toksearch/release/python3.10/<latest>   # NOT 1.6.1
"""

import os
import sys
import time
import traceback

import h5py
import numpy as np
import toksearch as ts
if not hasattr(ts, 'PtDataSignal'):
    from toksearch_d3d import PtDataSignal
    ts.PtDataSignal = PtDataSignal

import ecei_io
import ecei_utils
import paths_config
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

ROWS = 20   # vertical  (XX: 03-22)
COLS = 8    # horizontal (YY: 01-08)

# HDF5 chunk cache for channel-wise writes (keeps chunks in memory across channel loop)
HDF5_CHUNK_CACHE_NBYTES = int(2e9)


def generate_channel_list():
    """Returns list of clean channel names: ['LFS0301', 'LFS0302', ..., 'LFS2208']"""
    return [f"LFS{xx:02d}{yy:02d}" for xx in range(3, 23) for yy in range(1, 9)]


CHANNELS = generate_channel_list()


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


# ---------------------------------------------------------------------------
# CORE WORKER  (called inside @pipe.map for every shot)
# ---------------------------------------------------------------------------
def process_and_write_shot(rec, t_end_dict, output_dir, d_sample, rm_spikes_flag):
    """
    Processes one shot: for each channel, truncate -> downsample -> spike remove
    -> write directly to dset[:, row, col]. No full-shot buffer; stats accumulated
    as we go. Returns status dict.
    """
    _timing = os.environ.get("ECEI_TIMING", "0") == "1"
    t0 = time.time() if _timing else None
    shot = rec["shot"]
    out_path = os.path.join(output_dir, f"{shot}.h5")
    tmp_path = out_path + ".tmp"

    try:
        if ecei_io.check_assembled_file(out_path):
            print(f"  [{shot}] skipped", flush=True)
            return {"shot": shot, "status": "skipped"}

        t_limit_ms = None
        if t_end_dict and shot in t_end_dict:
            t_limit_ms = t_end_dict[shot] * 1000.0

        # ------------------------------------------------------------------
        # Pass 1: find reference time axis from first valid channel
        # ------------------------------------------------------------------
        time_ms = None
        for chan in CHANNELS:
            sig = rec.get(chan)
            if sig is None:
                continue
            raw_time = sig.get("times")
            if raw_time is not None and len(raw_time) >= 2:
                time_ms = raw_time
                break

        if time_ms is None:
            print(f"  [{shot}] no_data", flush=True)
            return {"shot": shot, "status": "no_data"}

        if t_limit_ms is not None:
            mask = time_ms <= t_limit_ms
            if not np.any(mask):
                print(f"  [{shot}] truncated_empty", flush=True)
                return {"shot": shot, "status": "truncated_empty"}
            time_ms = time_ms[mask]

        dt_sec = float(time_ms[1] - time_ms[0]) / 1000.0
        fs_hz = 1.0 / dt_sec if dt_sec > 0 else 0.0
        _, time_ms_ds = ecei_utils.downsample_signal(time_ms, time_ms, fs_hz, d_sample)
        n_time = len(time_ms_ds)
        freq = int(round(fs_hz / d_sample)) if d_sample >= 1 else int(round(fs_hz))
        if _timing:
            t_setup = time.time() - t0
            print(f"  [{shot}] timing setup=%.3fs" % t_setup, flush=True)

        # ------------------------------------------------------------------
        # Create HDF5 with dataset; write each channel directly into its slot
        # ------------------------------------------------------------------
        os.makedirs(output_dir, exist_ok=True)
        channel_sum = np.zeros((ROWS, COLS), dtype=np.float64)
        channel_sum_sq = np.zeros((ROWS, COLS), dtype=np.float64)
        channel_count = np.zeros((ROWS, COLS), dtype=np.float64)

        with h5py.File(tmp_path, "w", rdcc_nbytes=HDF5_CHUNK_CACHE_NBYTES) as f:
            f.create_group("0D")
            f.create_group("1D")
            g2d = f.create_group("2D")
            g_ecei = g2d.create_group("ecei")

            f.create_dataset("t_disrupt", data=0.0)
            f.create_dataset("t_start", data=0.0)
            g_ecei.create_dataset("freq", data=freq)

            dset = g_ecei.create_dataset(
                "signal",
                shape=(n_time, ROWS, COLS),
                dtype=np.float64,
                chunks=(min(n_time, 100_000), ROWS, COLS),
                compression="lzf",
            )

            for chan in CHANNELS:
                row, col = chan_to_grid_idx(chan)
                sig = rec.get(chan)
                if sig is None:
                    continue
                raw_data = sig.get("data")
                raw_time = sig.get("times")
                if raw_data is None or raw_time is None or len(raw_data) < 2:
                    continue

                if t_limit_ms is not None:
                    mask = raw_time <= t_limit_ms
                    raw_data = raw_data[mask]
                    raw_time = raw_time[mask]

                if len(raw_data) < 2:
                    continue

                proc_data, _ = ecei_utils.downsample_signal(
                    raw_data, raw_time, fs_hz, d_sample
                )
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
                dset[:actual_len, row, col] = proc_data[:actual_len]

                channel_sum[row, col] = np.sum(proc_data[:actual_len])
                channel_sum_sq[row, col] = np.sum(proc_data[:actual_len] ** 2)
                channel_count[row, col] = float(actual_len)

            if _timing:
                t_channel_loop = time.time() - t0 - t_setup
                print(f"  [{shot}] timing channel_loop=%.3fs" % t_channel_loop, flush=True)
            # Avoid division by zero for missing channels
            np.maximum(channel_count, 1.0, out=channel_count)
            means = channel_sum / channel_count
            vars_ = np.maximum(
                (channel_sum_sq / channel_count) - (means ** 2),
                0.0,
            )
            stds = np.sqrt(vars_)
            g_ecei.create_dataset("channel_means", data=means)
            g_ecei.create_dataset("channel_stds", data=stds)

        os.replace(tmp_path, out_path)
        if _timing:
            t_total = time.time() - t0
            t_finalize = t_total - t_setup - t_channel_loop
            print(f"  [{shot}] timing total=%.3fs finalize=%.3fs" % (t_total, t_finalize), flush=True)
        print(f"  [{shot}] ok", flush=True)
        return {"shot": shot, "status": "ok", "n_time": n_time}

    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        print(f"  [{shot}] error", flush=True)
        return {"shot": shot, "status": f"error: {traceback.format_exc()}"}


# ---------------------------------------------------------------------------
# MAIN  — build TokSearch pipeline and submit
# ---------------------------------------------------------------------------
def run_fetch_raw_job(
    shot_list,
    output_dir=None,
    clean_shots_file=None,
    t_end_file=None,
    d_sample=None,
    rm_spikes=None,
    batch_start=None,
    batch_end=None,
):
    """
    Run the FetchRawData pipeline for the given shot list.
    All arguments default to module config (env / paths_config) when None.
    """
    output_dir = output_dir or OUTPUT_DIR
    clean_shots_file = clean_shots_file or CLEAN_SHOTS_FILE
    t_end_file = t_end_file or T_END_FILE
    d_sample = d_sample if d_sample is not None else D_SAMPLE
    rm_spikes = rm_spikes if rm_spikes is not None else RM_SPIKES

    os.makedirs(output_dir, exist_ok=True)
    t_end_dict = load_t_end_dict(t_end_file)

    pipe = ts.Pipeline(shot_list)
    for chan in CHANNELS:
        pipe.fetch(chan, ts.PtDataSignal(chan))

    @pipe.map
    def process_shot(rec):
        return process_and_write_shot(
            rec,
            t_end_dict=t_end_dict,
            output_dir=output_dir,
            d_sample=d_sample,
            rm_spikes_flag=rm_spikes,
        )

    pipe.keep(["shot"])

    t0 = time.time()
    if "--ray" in sys.argv:
        pipe.compute_ray(
            memory_per_shot=int(12e9),
            num_cpus=resource_utils.get_allowed_cpus(),
        )
    else:
        results = pipe.compute_serial()
        statuses = {}
        for r in (results or []):
            if isinstance(r, dict):
                s = r.get("status", "unknown")
                statuses[s] = statuses.get(s, 0) + 1
        print(f"Results: {statuses}")

    elapsed = time.time() - t0
    n = len(shot_list)
    print(f"Done. {n} shots in {elapsed:.1f}s  ({elapsed / max(n, 1):.1f} s/shot)")
    return elapsed


def main():
    shots_all = paths_config.load_clean_shot_list(CLEAN_SHOTS_FILE)
    shots = shots_all[BATCH_START:BATCH_END]
    print(f"Shots: {len(shots)} (indices {BATCH_START}:{BATCH_END})")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Channels: {len(CHANNELS)},  D_SAMPLE={D_SAMPLE},  RM_SPIKES={RM_SPIKES}")

    run_fetch_raw_job(
        shots.tolist(),
        output_dir=OUTPUT_DIR,
        clean_shots_file=CLEAN_SHOTS_FILE,
        t_end_file=T_END_FILE,
        d_sample=D_SAMPLE,
        rm_spikes=RM_SPIKES,
    )


if __name__ == "__main__":
    main()
