import os
import h5py
import numpy as np
import shutil

# Re-export z-score spike removal so callers can use ecei_io for ECEI helpers
from ecei_utils import remove_spikes_custom_Z  # noqa: F401

def ensure_channel_dir(base_path, channel_name):
    """
    Ensures the directory for a specific channel exists.
    Example: base_path/LFS0301/
    
    Args:
        base_path (str): The root directory for data.
        channel_name (str): The channel name (e.g., '"LFS0301"').
        
    Returns:
        str: The full path to the channel directory.
    """
    # TokSearch often returns names like '"LFS0301"' with quotes.
    # We strip them so the folder name is clean: LFS0301
    clean_name = channel_name.replace('"', '').replace("'", "")
    full_path = os.path.join(base_path, clean_name)
    
    # Create the directory if it doesn't exist
    os.makedirs(full_path, exist_ok=True)
    return full_path

def check_file_exists(file_path):
    """
    Checks if a valid HDF5 file already exists.
    Returns True ONLY if the file exists and has keys (is not empty).
    """
    if not os.path.exists(file_path):
        return False
    
    # Check if file is non-empty or corrupted
    try:
        with h5py.File(file_path, 'r') as f:
            if len(f.keys()) > 0:
                return True
    except (OSError, IOError):
        # File exists but is likely corrupt (cannot open)
        return False
        
    return False


def check_assembled_file(file_path):
    """
    Validates that the file is a complete "Felipe Format" assembled ECEI file.
    Returns True only if the file opens, has 2D/ecei/signal with shape (T, 20, 8),
    dtype float64, T > 0, and has freq, channel_means, channel_stds.
    """
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        with h5py.File(file_path, "r") as f:
            if "2D" not in f or "ecei" not in f["2D"]:
                return False
            g = f["2D"]["ecei"]
            if "signal" not in g:
                return False
            sig = g["signal"]
            if sig.ndim != 3:
                return False
            T, R, C = sig.shape
            if R != 20 or C != 8 or T <= 0:
                return False
            if sig.dtype != np.float64:
                return False
            if "freq" not in g or "channel_means" not in g or "channel_stds" not in g:
                return False
        return True
    except (OSError, IOError, KeyError):
        return False


def check_assembled_channel_stats(file_path, rtol=1e-5, atol=1e-8):
    """
    Self-consistency check: recompute mean/std from 2D/ecei/signal and compare
    to stored channel_means and channel_stds. Catches accumulation bugs.
    Returns (passed: bool, msg: str). Uses numpy allclose with rtol/atol.
    """
    if not file_path or not os.path.exists(file_path):
        return False, "File missing or path empty"
    try:
        with h5py.File(file_path, "r") as f:
            g = f["2D"]["ecei"]
            sig = g["signal"][:]
            means_stored = g["channel_means"][:]
            stds_stored = g["channel_stds"][:]
        # Recompute: (20, 8) mean and std over time axis
        means_re = np.nanmean(sig, axis=0)
        # ddof=0 to match population variance as in pipeline
        stds_re = np.nanstd(sig, axis=0, ddof=0)
        # Replace nans so allclose does not fail
        means_re = np.where(np.isnan(means_re), 0.0, means_re)
        stds_re = np.where(np.isnan(stds_re), 0.0, stds_re)
        ok_means = np.allclose(means_stored, means_re, rtol=rtol, atol=atol)
        ok_stds = np.allclose(stds_stored, stds_re, rtol=rtol, atol=atol)
        if ok_means and ok_stds:
            return True, "channel_means/stds consistent with signal"
        diff_m = np.abs(means_stored - means_re)
        diff_s = np.abs(stds_stored - stds_re)
        return False, "means max_diff=%.2e stds max_diff=%.2e" % (
            float(np.max(diff_m)),
            float(np.max(diff_s)),
        )
    except Exception as e:
        return False, str(e)


def save_to_hdf5(file_path, channel_name, data=None, time=None, is_missing=False):
    """
    Saves the data to HDF5. Handles both valid data and 'missing' flags.
    
    Args:
        file_path: Full path to .hdf5 file.
        channel_name: Name of the channel (e.g. LFS0301).
        data: Numpy array of voltage data (optional if is_missing=True).
        time: Numpy array of time data (optional if is_missing=True).
        is_missing: If True, saves a special 'missing' flag instead of data.
    """
    # Clean channel name for HDF5 dataset key
    clean_name = channel_name.replace('"', '').replace("'", "")
    
    # Mode 'w' will overwrite if exists
    try:
        with h5py.File(file_path, 'w') as f:
            if is_missing:
                # Standard convention for missing data found in original code
                # It saves a dataset named 'missing_CHANNEL' with value [-1.0]
                f.create_dataset(f'missing_{clean_name}', data=np.array([-1.0]))
            else:
                if data is not None:
                    f.create_dataset(clean_name, data=data)
                if time is not None:
                    f.create_dataset('time', data=time)
                    
    except Exception as e:
        print(f"Error saving {file_path}: {e}")
        # Safety: If save crashes halfway, delete the partial file 
        # so we don't think it's 'done' later.
        if os.path.exists(file_path):
            os.remove(file_path)

# ECEI detector geometry (20 vertical rows x 8 horizontal columns = 160 channels)
ECEI_ROWS = 20
ECEI_COLS = 8


def check_assembled_content(
    file_path,
    blank_atol=0.0,
    min_bytes=50_000_000,
    suspect_zero_frac=0.10,
    blank_zero_frac=0.95,
):
    """
    Content-level QA for an assembled ECEI file, complementing the *structural*
    check in ``check_assembled_file()``.

    Detects silently zero-filled / blank channels -- the FDP/Pelican CDN-miss
    failure mode where a shot exists on D3D but the pipeline writes zeros -- WITHOUT
    loading the full multi-GB signal. A real ECEI channel has non-zero variance,
    so a channel whose stored ``channel_stds`` and ``channel_means`` are both ~0 is
    treated as blank.

    Returns a dict:
        ok            bool   -- structurally valid AND status == 'good'
        status        str    -- 'good' | 'suspect' | 'blank' | 'invalid' | 'missing'
        n_good        int    -- channels with signal (0..160)
        n_total       int    -- 160
        zero_fraction float  -- fraction of all-zero (blank) channels
        bytes         int    -- file size on disk
        reason        str
    """
    n_total = ECEI_ROWS * ECEI_COLS
    if not file_path or not os.path.exists(file_path):
        return {"ok": False, "status": "missing", "n_good": 0, "n_total": n_total,
                "zero_fraction": 1.0, "bytes": 0, "n_time": 0, "reason": "file missing"}
    try:
        nbytes = os.path.getsize(file_path)
    except OSError:
        nbytes = 0
    if not check_assembled_file(file_path):
        return {"ok": False, "status": "invalid", "n_good": 0, "n_total": n_total,
                "zero_fraction": 1.0, "bytes": nbytes, "n_time": 0,
                "reason": "failed check_assembled_file"}
    try:
        with h5py.File(file_path, "r") as f:
            g = f["2D"]["ecei"]
            means = g["channel_means"][:]
            stds = g["channel_stds"][:]
            n_time = int(g["signal"].shape[0])
    except (OSError, IOError, KeyError) as e:
        return {"ok": False, "status": "invalid", "n_good": 0, "n_total": n_total,
                "zero_fraction": 1.0, "bytes": nbytes, "n_time": 0, "reason": str(e)}

    blank_mask = (np.abs(stds) <= blank_atol) & (np.abs(means) <= blank_atol)
    n_blank = int(np.count_nonzero(blank_mask))
    n_good = n_total - n_blank
    zero_fraction = n_blank / float(n_total)

    reason = ""
    if n_good == 0 or zero_fraction >= blank_zero_frac:
        # (near-)fully zero-filled: the real CDN-miss blank signature.
        status = "blank"
        reason = f"{n_blank}/{n_total} channels all-zero"
    elif zero_fraction > suspect_zero_frac:
        status = "suspect"
        reason = f"{n_blank}/{n_total} channels all-zero (partial)"
    elif nbytes < min_bytes:
        # All channels present but unusually small on disk: likely a genuinely
        # short shot, but flag for a human/QA look rather than trusting blindly.
        status = "suspect"
        reason = f"small file ({nbytes} bytes, {n_time} samples) but all channels present"
    else:
        status = "good"

    return {"ok": status == "good", "status": status, "n_good": n_good,
            "n_total": n_total, "zero_fraction": round(zero_fraction, 4),
            "bytes": nbytes, "n_time": n_time, "reason": reason}
