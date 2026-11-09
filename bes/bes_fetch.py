"""
Self-contained BES (Beam Emission Spectroscopy) fetcher for DIII-D shots.

Fetches all 64 BES channels (besfu01..besfu64) via TokSearch/PTDATA and writes
one HDF5 per shot with:

  - a SHARED top-level `/times` dataset (the 1 MHz timebase is written ONCE
    rather than 64 times, saving ~350 MB per shot)
  - per-channel `/besfuNN/data` as float32 (BES is calibrated voltage in the
    ~-1..+1 range; float64 is wasteful, float32 carries plenty of precision)

Result: ~150 MB per shot on disk, vs ~975 MB if the per-channel times are
duplicated and data is stored as float64.

This module is intentionally decoupled from the rest of the ECEI-Data
repository (does NOT import physics_config, physics_io, paths_config,
run_physics_download, or resource_utils). Only depends on:

    numpy, h5py, toksearch  (toksearch needs PTDATA access for BES)

On Polaris (no local PTDATA, fetch goes via Pelican/XRootD through a
login-node HTTPS proxy), there are two performance paths:

  - Direct remote fetch (prestage=False):
      Each PtDataSignal call is a network round-trip per channel.
      Measured: ~2.5 s/channel * 64 channels = ~160 s/shot. Easy to read
      but kills throughput.

  - Prestaged + parallel local fetch (prestage=True, default):
      Per shot, one xrdcp of the underlying .BES archive into a local cache,
      then ptdata64 extracts all 64 channels in parallel via a thread pool
      (the C extension releases the GIL). Measured for ECEI's analogous
      setup: 191 s -> ~25-30 s per shot. Same trick applied here.

Public API:
    BES_CHANNELS, BES_KEYS, BES_PT_NAMES   module-level constants
    get_bes_signal_dict()                  {key: PtDataSignal} for direct fetch
    get_bes_path(root, shot, sharded)      shard-aware path helper
    bes_shot_complete(root, shot, ...)     skip predicate
    write_bes_shot(rec, root, sharded)     per-shot writer
    fetch_bes(shots, root, ...)            driver (TokSearch pipeline + Ray)
"""

from __future__ import annotations

import logging
import os
import sys
import time

import h5py
import numpy as np

try:
    import toksearch as ts
except ImportError:
    ts = None  # caller will get a clear error from get_bes_signal_dict / fetch_bes
else:
    # Some toksearch builds (e.g. the FDP pixi env on Polaris) ship
    # PtDataSignal under toksearch_d3d instead of as a top-level attribute.
    # Mirror what the ECEI fetcher does so the rest of this module can just
    # call ts.PtDataSignal(...) regardless of which build is installed.
    if not hasattr(ts, "PtDataSignal"):
        try:
            from toksearch_d3d import PtDataSignal as _PtDataSignal
            ts.PtDataSignal = _PtDataSignal
        except ImportError:
            pass


# --- BES channel definitions ------------------------------------------------

# 64 BES fast channels: HDF5 key (lowercase) -> PtData node name (uppercase).
BES_CHANNELS = [("besfu{:02d}".format(i), "BESFU{:02d}".format(i)) for i in range(1, 65)]
BES_KEYS = [k for k, _ in BES_CHANNELS]
BES_PT_NAMES = [pt for _, pt in BES_CHANNELS]
_PT_TO_KEY = {pt: k for k, pt in BES_CHANNELS}


def get_bes_signal_dict():
    """Return {hdf5_key: toksearch.PtDataSignal} for the 64 BES channels."""
    if ts is None or not hasattr(ts, "PtDataSignal"):
        raise RuntimeError(
            "toksearch.PtDataSignal is not importable. BES is PTDATA-only; you need "
            "a TokSearch install with PTDATA access (either local PTDATA_ROOT + "
            "TOKSEARCH_INDEX_* env vars, or the FDP pixi env on Polaris with "
            "PTDATA_LOC/PTDATA_JSON_INDEX_DIR set via `fdp run`)."
        )
    return {key: ts.PtDataSignal(name) for key, name in BES_CHANNELS}


# --- HDF5 layout ------------------------------------------------------------

def get_bes_path(root: str, shot: int, sharded: bool = True) -> str:
    """Return the on-disk path for one shot.

    sharded=True (default): {root}/{shot//1000}xxx/{shot}.h5
    sharded=False:          {root}/{shot}.h5
    """
    shot = int(shot)
    if sharded:
        return os.path.join(root, "{}xxx".format(shot // 1000), "{}.h5".format(shot))
    return os.path.join(root, "{}.h5".format(shot))


def bes_shot_complete(
    root: str,
    shot: int,
    sharded: bool = True,
    min_channels: int = 1,
) -> bool:
    """Return True if shot's BES file has >= `min_channels` BES groups + usable timebase.

    Default `min_channels=1` means "any BES at all"; set to 64 to require the
    full array. Used as a skip predicate by fetch_bes().
    """
    path = get_bes_path(root, shot, sharded=sharded)
    if not os.path.exists(path):
        return False
    try:
        with h5py.File(path, "r") as f:
            n_have = sum(
                1 for k in BES_KEYS
                if k in f and "data" in f[k] and f[k]["data"].size > 0
            )
            if n_have < min_channels:
                return False
            if "times" in f and f["times"].size > 0:
                return True
            # Fallback layout (per-channel times): require every present channel to carry its own.
            for k in BES_KEYS:
                if k in f and "data" in f[k] and "times" not in f[k]:
                    return False
            return True
    except (OSError, IOError):
        return False


def write_bes_shot(rec, root: str, sharded: bool = True) -> None:
    """Write one TokSearch record's BES into the dedup + float32 layout.

    File layout (per shot):

        /                    attrs: shot, n_channels, n_samples, sample_rate_hz,
                                    t_start_ms, t_end_ms, dtype, shared_times, source
        /times               (n_samples,) float64   shared timebase, written ONCE
        /besfu01/data        (n_samples,) float32   gzip-4
        /besfu02/data        ...
        ...
        /besfu64/data

    Idempotent: existing groups are never overwritten. If `rec` only contains a
    subset of channels, only that subset is written; subsequent calls add more.

    If any two channels disagree on their timebase (rare PTDATA quirk), the
    writer falls back to per-channel `besfuNN/times` arrays and sets the
    top-level attribute `shared_times=False`.
    """
    shot = int(rec["shot"])
    path = get_bes_path(root, shot, sharded=sharded)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Collect channels and validate timebases match.
    channels = []
    reference_times = None
    times_match = True
    for key in BES_KEYS:
        if key not in rec:
            continue
        sig = rec[key]
        if sig is None:
            continue
        vals = sig.get("data")
        times = sig.get("times")
        if vals is None or times is None:
            continue
        if hasattr(vals, "size") and vals.size == 0:
            continue
        vals32 = np.asarray(vals, dtype=np.float32)
        times64 = np.asarray(times, dtype=np.float64)
        if reference_times is None:
            reference_times = times64
        elif times_match and (
            times64.shape != reference_times.shape
            or not np.array_equal(times64, reference_times)
        ):
            times_match = False
        channels.append((key, vals32, times64))

    if not channels:
        print("  [{}] no_bes: 0/64 channels returned data (shot likely has no "
              "BES fast-channel data)".format(shot), flush=True)
        return

    mode = "a" if os.path.exists(path) else "w"
    with h5py.File(path, mode) as f:
        if "shot" not in f.attrs:
            f.attrs["shot"] = shot
        f.attrs["source"] = "PTDATA"
        f.attrs["dtype"] = "float32"
        f.attrs["shared_times"] = bool(times_match)
        n_samples = reference_times.shape[0] if times_match else 0
        f.attrs["n_samples"] = int(n_samples)
        if reference_times.size >= 2:
            f.attrs["t_start_ms"] = float(reference_times[0])
            f.attrs["t_end_ms"] = float(reference_times[-1])
            dt_ms = (reference_times[-1] - reference_times[0]) / (reference_times.size - 1)
            f.attrs["sample_rate_hz"] = float(1e3 / dt_ms) if dt_ms > 0 else 0.0

        if times_match and "times" not in f:
            f.create_dataset(
                "times", data=reference_times, compression="gzip", compression_opts=4
            )

        for key, vals32, times64 in channels:
            if key in f:
                continue
            grp = f.create_group(key)
            grp.create_dataset(
                "data", data=vals32, compression="gzip", compression_opts=4
            )
            if not times_match:
                grp.create_dataset(
                    "times",
                    data=times64.astype(np.float32),
                    compression="gzip",
                    compression_opts=4,
                )
        f.attrs["n_channels"] = int(sum(1 for k in f.keys() if k.startswith("besfu")))


# --- Ray / FDP env passthrough ---------------------------------------------

# Env vars the driver (PBS script + `fdp run` wrapper) sets up that the Ray
# workers also need to fetch via Pelican/XRootD. Mirrors the list in
# FetchRawDataChannelWise.ray_init_kwargs_for_fdp.
_FDP_PASSTHROUGH_ENV = (
    "ALL_PROXY", "all_proxy",
    "HTTPS_PROXY", "https_proxy",
    "HTTP_PROXY",  "http_proxy",
    "NO_PROXY",    "no_proxy",
    "BEARER_TOKEN",
    "CONDA_PREFIX", "PREFIX",
    "PTDATA_LOC", "PTDATA_JSON_INDEX_DIR",
    "PTDATA_PLUGIN_LIB", "PTDATA_LIBRARY",
    "XRD_PLUGINCONFDIR",
    "X509_CERT_FILE",
    "XRDCP_ALLOW_HTTP",
    "XRD_PELICANUSEAUTHHEADERS",
    "XRD_CURLDISABLEPREFETCH",
    "default_tree_path",
    "LD_LIBRARY_PATH",
    "SYS_D3", "SYS_D3_DELIM",
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
    # Local-PTDATA path (Polaris fallback / off-Polaris hosts):
    "PTDATA_ROOT",
    "TOKSEARCH_INDEX_FILE",
    "TOKSEARCH_INDEX_DIR",
)


def ray_init_kwargs_for_fdp(num_cpus=None):
    """Build ray.init kwargs that forward FDP/Pelican env vars to workers.

    Polaris compute nodes do not inherit the driver's full environment; without
    this, Ray-side PTDATA fetches fail with "auth required" or "no plugin".
    On hosts where these vars are unset (e.g. local-PTDATA install), this is a
    no-op passthrough.
    """
    kwargs = {}
    if os.environ.get("TMPDIR"):
        kwargs["_temp_dir"] = os.environ["TMPDIR"]

    env_vars = {k: os.environ[k] for k in _FDP_PASSTHROUGH_ENV if os.environ.get(k)}
    if env_vars:
        kwargs["runtime_env"] = {"env_vars": env_vars}

    kwargs.setdefault("logging_level", logging.ERROR)

    if num_cpus is not None:
        kwargs["num_cpus"] = int(num_cpus)

    return kwargs


# --- Driver -----------------------------------------------------------------

def _run_pipeline_remote(batch, num_workers):
    """One direct-PTDATA Ray pipeline for `batch`. 64 sequential channel
    fetches per shot through PtDataSignal. Slow on Polaris (~160 s/shot)
    but works anywhere TokSearch can see PTDATA."""
    pipe = ts.Pipeline(list(batch))
    signals = get_bes_signal_dict()
    for name, sig in signals.items():
        pipe.fetch(name, sig)
    return pipe


def _run_pipeline_prestaged(batch, stager, fetch_threads):
    """One prestaged Ray pipeline for `batch`. Assumes `stager.prestage_shots`
    has already run for these shots and PTDATA_LOC/SYS_D3 are set on both the
    driver and via Ray runtime_env.
    """
    import bes_prestage  # local import keeps direct path import-light
    pipe = ts.Pipeline(list(batch))
    _pt_names = BES_PT_NAMES
    _stg = stager
    _nt = int(fetch_threads)

    @pipe.map
    def fetch_local(rec, _pt=_pt_names, _s=_stg, _nt=_nt):
        ch_data = bes_prestage.parallel_fetch_channels(
            rec["shot"], _pt, _s, max_threads=_nt,
        )
        for pt_name, data in ch_data.items():
            key = _PT_TO_KEY.get(pt_name, pt_name.lower())
            rec[key] = data
        return rec

    return pipe


def fetch_bes(
    shots,
    root: str,
    num_workers: int = 8,
    sharded: bool = True,
    require_full: bool = False,
    prestage: bool = True,
    shot_batch_size: int = 50,
    prestage_concurrency: int = 8,
    fetch_threads: int = 8,
) -> None:
    """Fetch BES for the given iterable of shots into `root`.

    Args:
        shots:                iterable of shot numbers (int-castable).
        root:                 output directory. Sharded layout under
                              {root}/{shot//1000}xxx/.
        num_workers:          Ray worker count. ~5 GB RAM per worker in flight.
        sharded:              True (default) for {root}/Nxxx/shot.h5 layout.
        require_full:         True = only skip shots with all 64 channels.
                              False (default) = skip if >=1 channel + timebase.
        prestage:             True (default) = pre-download .BES archives and
                              read channels locally in parallel (~5-7x faster
                              on Polaris). False = direct remote PtDataSignal
                              fetch (works anywhere, slow on Polaris).
        shot_batch_size:      Shots per prestage+pipeline batch. Smaller =
                              less peak local-cache disk, faster failure
                              feedback; larger = better amortized Ray startup.
        prestage_concurrency: Concurrent xrdcp downloads in the prestage step.
        fetch_threads:        Per-Ray-worker thread count for parallel local
                              channel extraction (only used when prestage=True).
    """
    if ts is None:
        raise RuntimeError(
            "toksearch is not importable. See get_bes_signal_dict() for details."
        )
    os.makedirs(root, exist_ok=True)

    min_chan = 64 if require_full else 1
    shots = list(shots)
    todo = [
        int(s) for s in shots
        if not bes_shot_complete(root, int(s), sharded=sharded, min_channels=min_chan)
    ]
    n_skipped = len(shots) - len(todo)
    if n_skipped:
        print("BES: skipping {} shots already done (min_channels={}).".format(
            n_skipped, min_chan
        ))
    if not todo:
        print("BES: nothing to fetch.")
        return

    print("BES: fetching {} channels for {} shots -> {}".format(
        len(BES_KEYS), len(todo), root
    ))
    print("BES workers={}  prestage={}  shot_batch_size={}  fetch_threads={}".format(
        num_workers, prestage, shot_batch_size, fetch_threads,
    ))

    # If prestaging is requested but bes_prestage / pyxrootd isn't importable,
    # fall back to the direct remote path with a clear warning.
    stager = None
    if prestage:
        try:
            import bes_prestage  # noqa: F401
            stager = bes_prestage.ShotPreStager(
                channels=BES_PT_NAMES,
                max_concurrent=int(prestage_concurrency),
            )
            print("BES: prestage cache: {}".format(stager.cache_dir))
        except Exception as e:
            print("BES: prestage unavailable ({}); falling back to direct remote fetch.".format(e))
            stager = None
            prestage = False

    def _attach_writer(pipe):
        @pipe.map
        def process(rec):
            shot = rec["shot"]
            try:
                write_bes_shot(rec, root, sharded=sharded)
                print("[{}] BES shot {}".format(time.strftime("%H:%M:%S"), shot))
                sys.stdout.flush()
            except Exception as e:
                print("Failed shot {} (BES): {}".format(shot, e))
                sys.stdout.flush()
        pipe.keep([])

    n_batches = (len(todo) + shot_batch_size - 1) // shot_batch_size
    t0 = time.time()
    n_done = 0

    for bi in range(n_batches):
        batch = todo[bi * shot_batch_size : (bi + 1) * shot_batch_size]
        print("--- BES batch {}/{}  ({} shots) ---".format(bi + 1, n_batches, len(batch)))
        bt0 = time.time()

        saved_env = {}
        try:
            if stager is not None:
                t_ps = time.time()
                stager.prestage_shots(batch)
                print("  [prestage] batch {}/{}: {:.1f}s".format(
                    bi + 1, n_batches, time.time() - t_ps,
                ))
                # Driver-side env for any in-process pyxrootd / ptdata use.
                for k, v in stager.get_env_overrides().items():
                    saved_env[k] = os.environ.get(k)
                    os.environ[k] = v
                for k in ("PTDATA_JSON_INDEX_DIR", "PTDATA_PLUGIN_LIB"):
                    saved_env[k] = os.environ.pop(k, None)
                pipe = _run_pipeline_prestaged(batch, stager, fetch_threads)
            else:
                pipe = _run_pipeline_remote(batch, num_workers)

            _attach_writer(pipe)

            try:
                ray_kwargs = ray_init_kwargs_for_fdp(num_cpus=num_workers)
                if stager is not None:
                    # Ray workers also need the local-PTDATA env so ptdata64
                    # reads from cache instead of trying Pelican again.
                    env_update = ray_kwargs.setdefault("runtime_env", {}).setdefault("env_vars", {})
                    env_update["PTDATA_LOC"] = "0"
                    env_update["SYS_D3"] = str(stager.cache_dir)
                    env_update.pop("PTDATA_JSON_INDEX_DIR", None)
                    env_update.pop("PTDATA_PLUGIN_LIB", None)

                # ~5 GB peak per BES shot (64 chan x ~16 MB raw x in-flight copies).
                pipe.compute_ray(
                    memory_per_shot=int(5e9),
                    ray_init_kwargs=ray_kwargs,
                )
                try:
                    import ray as _ray
                    _ray.shutdown()
                except Exception:
                    pass
            except Exception as e:
                print("Ray failed (BES batch {}), serial fallback: {}".format(bi + 1, e))
                pipe.compute_serial()
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        n_done += len(batch)
        bt = time.time() - bt0
        print("  [batch {}/{}] done in {:.1f}s ({:.1f}s/shot)".format(
            bi + 1, n_batches, bt, bt / max(1, len(batch)),
        ))

    elapsed = time.time() - t0
    print("BES fetch total: {:.1f}s ({:.1f}s/shot, n={})".format(
        elapsed, elapsed / max(1, n_done), n_done,
    ))
