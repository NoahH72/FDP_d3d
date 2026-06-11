"""
Physics HDF5 and sidecar I/O.
write_physics_shot: full HDF5 write + optional {shot}_stats.csv.
append_physics_shot: append signal groups to existing HDF5 (for split slow/fast pass 2).

Sharded layout (matches rodriguezj): {root}/{shot//1000}xxx/{shot}.h5 and {shot}_stats.csv
"""
import csv
import os
import shutil
import numpy as np
import h5py


# Profile signals that carry dims embedded in the same record dict
# (MdsSignal(..., dims=("rho","times")) under FDP/Pelican returns
# {"data": ..., "rho": ..., "times": ..., "units": ...}).
# For these signals we write HDF5 datasets "data", "times", "rho" just like
# edensfit, but sourced from inside the signal record rather than from separate
# *_time / *_rho top-level record entries.
_PROFILE_SIGS_EMBEDDED_DIMS = ("etempfit", "itempfit", "trotfit")


def get_physics_shard_dir(root, shot):
    """Return shard dir path for shot: {root}/{shot//1000}xxx."""
    shard = str(int(shot) // 1000) + "xxx"
    return os.path.join(root, shard)


def get_physics_h5_path(root, shot):
    """Return full HDF5 path for shot: {root}/{shot//1000}xxx/{shot}.h5."""
    shard_dir = get_physics_shard_dir(root, shot)
    return os.path.join(shard_dir, str(int(shot)) + ".h5")


def _write_one_signal(grp, sig_name, vals, times, rec, f):
    """Write one signal group into open HDF5 file f.

    Three axis-handling modes:
      - edensfit: dims come from separate rec["edensfit_time"]/rec["edensfit_rho"]
        records (legacy remote-MDS pattern with DIM_OF TDI).
      - _PROFILE_SIGS_EMBEDDED_DIMS (etempfit/itempfit/trotfit): dims come from
        inside the signal's own record dict, keys "times" and "rho"
        (FDP/Pelican pattern with MdsSignal dims=).
      - other signals: at most a 1-D "times" dataset, no "rho".
    """
    if np.isscalar(vals) or vals.ndim == 0:
        grp.create_dataset("data", data=vals)
    else:
        grp.create_dataset("data", data=vals, compression="gzip")

    if sig_name == "edensfit":
        edensfit_time = rec.get("edensfit_time")
        edensfit_rho = rec.get("edensfit_rho")
        time_arr = edensfit_time.get("data") if edensfit_time is not None else None
        rho_arr = edensfit_rho.get("data") if edensfit_rho is not None else None
        if time_arr is not None and hasattr(time_arr, "size") and time_arr.size > 0 and vals.shape[0] == len(time_arr):
            grp.create_dataset("times", data=time_arr, compression="gzip")
        elif times is not None:
            if np.isscalar(times) or times.ndim == 0:
                grp.create_dataset("times", data=times)
            else:
                grp.create_dataset("times", data=times, compression="gzip")
        if rho_arr is not None and vals.ndim > 1 and vals.shape[1] == len(rho_arr):
            grp.create_dataset("rho", data=rho_arr, compression="gzip")
    elif sig_name in _PROFILE_SIGS_EMBEDDED_DIMS:
        try:
            sig_obj = rec[sig_name]
        except (KeyError, Exception):
            sig_obj = None
        if sig_obj is None:
            sig_obj = {}
        time_arr = sig_obj.get("times") if hasattr(sig_obj, "get") else None
        rho_arr = sig_obj.get("rho") if hasattr(sig_obj, "get") else None
        if time_arr is not None and hasattr(time_arr, "size") and time_arr.size > 0 \
                and vals.ndim >= 1 and vals.shape[0] == len(time_arr):
            grp.create_dataset("times", data=time_arr, compression="gzip")
        if rho_arr is not None and hasattr(rho_arr, "size") and rho_arr.size > 0 \
                and vals.ndim > 1 and vals.shape[1] == len(rho_arr):
            grp.create_dataset("rho", data=rho_arr, compression="gzip")
    elif times is not None:
        if np.isscalar(times) or times.ndim == 0:
            grp.create_dataset("times", data=times)
        else:
            grp.create_dataset("times", data=times, compression="gzip")


def _stats_row(shot, sig_name, vals, times):
    """One row for sidecar CSV."""
    if hasattr(vals, "ndim") and vals.ndim == 0:
        length = 1
        ram_bytes = vals.nbytes if hasattr(vals, "nbytes") else 0
        val_mean = float(vals)
        val_std = 0.0
    else:
        length = int(vals.shape[0]) if hasattr(vals, "shape") else 0
        ram_bytes = int(vals.nbytes) + (int(times.nbytes) if times is not None and hasattr(times, "nbytes") else 0)
        val_mean = float(np.mean(vals))
        val_std = float(np.std(vals))
    if times is not None and hasattr(times, "__len__") and len(times) > 1:
        mean_dt = (float(times[-1]) - float(times[0])) / (len(times) - 1)
    else:
        mean_dt = float("nan")
    return {
        "shot": shot,
        "signal": sig_name,
        "length": length,
        "ram_bytes": ram_bytes,
        "mean_dt": mean_dt,
        "val_mean": val_mean,
        "val_std": val_std,
    }


def write_physics_shot(rec, save_dir, write_sidecar=True):
    """
    Write one shot to HDF5; optionally write {shot}_stats.csv after success.
    Same structure as legacy: groups per signal, edensfit with explicit time/rho.
    """
    shot = rec["shot"]
    file_path = os.path.join(save_dir, f"{shot}.h5")
    stats_rows = []

    with h5py.File(file_path, "w") as f:
        f.attrs["shot"] = shot
        for sig_name, data_obj in rec.items():
            if sig_name in ["shot", "stats", "status", "disruption_label"]:
                continue
            if sig_name in ("edensfit_time", "edensfit_rho"):
                continue
            if data_obj is None:
                continue
            vals = data_obj.get("data")
            times = data_obj.get("times")
            if vals is None:
                continue
            if hasattr(vals, "size") and vals.size == 0:
                continue
            grp = f.create_group(sig_name)
            _write_one_signal(grp, sig_name, vals, times, rec, f)
            if write_sidecar:
                try:
                    times_for_stats = times
                    if sig_name == "edensfit" and rec.get("edensfit_time") is not None:
                        times_for_stats = rec["edensfit_time"].get("data")
                    stats_rows.append(_stats_row(shot, sig_name, vals, times_for_stats))
                except Exception:
                    pass

    if write_sidecar and stats_rows:
        try:
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        except OSError:
            file_size_mb = 0.0
        sidecar_path = os.path.join(save_dir, f"{shot}_stats.csv")
        with open(sidecar_path, "w", newline="") as out:
            w = csv.DictWriter(
                out,
                fieldnames=["shot", "signal", "length", "ram_bytes", "mean_dt", "val_mean", "val_std", "file_size_mb"],
            )
            w.writeheader()
            for row in stats_rows:
                row["file_size_mb"] = file_size_mb
                w.writerow(row)


def append_physics_shot(rec, save_dir, signal_keys, sharded=False):
    """
    Append signal groups to existing {shot}.h5. Opens file in 'a'.
    Only writes groups for keys in signal_keys. If a group already exists we skip it
    (no delete) to avoid HDF5 segfaults on corrupt or legacy files.

    sharded: if True, save_dir is the root and path is {root}/{shot//1000}xxx/{shot}.h5
    """
    shot = rec["shot"]
    if sharded:
        file_path = get_physics_h5_path(save_dir, shot)
    else:
        file_path = os.path.join(save_dir, f"{shot}.h5")
    if not os.path.exists(file_path):
        return
    with h5py.File(file_path, "a") as f:
        for sig_name in signal_keys:
            if sig_name not in rec:
                continue
            data_obj = rec[sig_name]
            if data_obj is None:
                continue
            vals = data_obj.get("data")
            times = data_obj.get("times")
            if vals is None:
                continue
            if hasattr(vals, "size") and vals.size == 0:
                continue
            if sig_name in f:
                continue
            grp = f.create_group(sig_name)
            _write_one_signal(grp, sig_name, vals, times, rec, f)


def shot_has_all_extras(save_dir, shot, signal_keys, sharded=False):
    """
    Return True if the shot's HDF5 already has every key in signal_keys as a group
    with a non-empty 'data' dataset. Used to skip shots that already have extras (idempotent).
    """
    if sharded:
        file_path = get_physics_h5_path(save_dir, shot)
    else:
        file_path = os.path.join(save_dir, f"{int(shot)}.h5")
    if not os.path.exists(file_path):
        return False
    try:
        with h5py.File(file_path, "r") as f:
            for sig_name in signal_keys:
                if sig_name not in f:
                    return False
                grp = f[sig_name]
                if "data" not in grp:
                    return False
                d = grp["data"]
                if hasattr(d, "size") and d.size == 0:
                    return False
        return True
    except (OSError, IOError):
        return False


def ensure_shot_copied(source_root, target_root, shot):
    """
    Copy {source_root}/{shot//1000}xxx/{shot}.h5 to the equivalent path under
    target_root, preserving the sharded layout. Idempotent: if the target
    already exists we leave it untouched.

    Returns a tuple (target_path, status) where status is one of:
      - "exists": target was already in place, nothing to do
      - "copied": file was freshly copied from source
      - "source_missing": no source file exists (caller should skip the shot)

    Copies go via a .tmp suffix then atomic rename, so partial copies are never
    visible to concurrent readers/verifiers.
    """
    shot_int = int(shot)
    target_path = get_physics_h5_path(target_root, shot_int)
    if os.path.exists(target_path):
        return target_path, "exists"
    source_path = get_physics_h5_path(source_root, shot_int)
    if not os.path.exists(source_path):
        return target_path, "source_missing"
    os.makedirs(get_physics_shard_dir(target_root, shot_int), exist_ok=True)
    tmp_path = target_path + ".tmp"
    try:
        shutil.copy2(source_path, tmp_path)
        os.replace(tmp_path, target_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return target_path, "copied"


def physics_shot_complete(save_dir, shot, use_sidecar=False, sharded=False):
    """
    Return True if this shot is considered complete.
    use_sidecar: if True, check for {shot}_stats.csv; else use ecei_io.check_file_exists for {shot}.h5.
    sharded: if True, save_dir is the root and path is {root}/{shot//1000}xxx/{shot}.h5 or _stats.csv
    """
    import ecei_io
    shot_int = int(shot)
    if sharded:
        shard_dir = get_physics_shard_dir(save_dir, shot)
        if use_sidecar:
            path = os.path.join(shard_dir, f"{shot_int}_stats.csv")
            return os.path.isfile(path)
        path = get_physics_h5_path(save_dir, shot)
        return ecei_io.check_file_exists(path)
    if use_sidecar:
        path = os.path.join(save_dir, f"{shot_int}_stats.csv")
        return os.path.isfile(path)
    path = os.path.join(save_dir, f"{shot_int}.h5")
    return ecei_io.check_file_exists(path)
