"""
Signal-processing utilities extracted from ECEI.py for use in a
rewritten ECEI pipeline. Other logic (I/O, SNR, file conversion, etc.) lives
in other modules; this file contains only the three helpers below.

Functions:
  - filter_signal: Low-pass anti-aliasing filter before decimation.
  - downsample_signal: Filter then decimate by an integer factor (causal).
  - remove_spikes_custom_Z: Causal rolling-window Z-score spike removal.
  - remove_spikes_custom_Z_count: Same but returns (cleaned_copy, n_replaced).

The z-score inner loop has two backends: a Numba JIT version
(_zscore_core_numba) for ~331x speedup, and a pure-Python fallback
(_zscore_core_python). The Numba path is used automatically when numba
is available (HAS_NUMBA flag).

Call-site note: downsample_signal uses argument order
  (signal, time, orig_sample_rate, decimation_factor)
with time as the 2nd argument. This differs from ECEI.py, where time is
the 4th argument with default np.array([]).
"""
import numpy as np
import scipy.signal

try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False


def filter_signal(signal, orig_sample_rate, decimation_factor):
    """
    Applies a low-pass anti-aliasing filter to the signal.

    Used before decimation so that high frequencies above the new Nyquist
    limit are removed; otherwise they would alias. The target sample rate
    is orig_sample_rate / decimation_factor; the cutoff is set below that
    Nyquist (at target/2.25) for a smooth rolloff. The filter is strictly
    causal (uses only past and current samples), matching ECEI.py
    """
    # No decimation -> no filtering needed. Change from ECEI.py: old code
    # had no guard and always ran the filter.
    if decimation_factor <= 1:
        return signal

    # Target rate after decimation (Hz).
    target_sample_rate = orig_sample_rate / decimation_factor
    # Cutoff below Nyquist for rolloff (target/2.25).
    cutoff_freq = target_sample_rate / 2.25
    # Kaiser filter length; same formula as ECEI.py: decimation_factor*4+1.
    num_taps = int(decimation_factor * 4 + 1)

    # Same design as ECEI.py: FIR low-pass, Kaiser window beta=2, then
    # causal convolution.
    filter_coeffs = scipy.signal.firwin(
        num_taps,
        cutoff_freq,
        window=('kaiser', 2),
        fs=orig_sample_rate
    )
    return scipy.signal.lfilter(filter_coeffs, [1.0], signal)

def downsample_signal(signal, time, orig_sample_rate, decimation_factor):
    """
    Downsamples a signal by an integer factor: first applies a causal
    low-pass anti-aliasing filter, then keeps every decimation_factor-th
    sample.

    Parameter order: (signal, time, orig_sample_rate, decimation_factor).
    time may be None or empty; in that case it is returned unchanged.

    Changes from ECEI.py:
      - Argument order: here time is 2nd; in ECEI.py it is 4th with
        default np.array([]).
      - When decimation_factor > 10: we still filter and decimate (and
        warn); ECEI.py only warned and then used an undefined
        filtered_signal (bug).
      - Time handling: we support time is None; ECEI.py assumed an
        array and used time.shape[0].
    """
    if decimation_factor == 1:
        return signal, time

    # We still run the filter and decimate; ECEI.py did not set
    # filtered_signal here, causing NameError.
    if decimation_factor > 10:
        print(f"Warning: Decimation factor {decimation_factor} is high.")

    filtered_signal = filter_signal(signal, orig_sample_rate, decimation_factor)
    sig_ds = filtered_signal[::decimation_factor]

    # Support None or empty time; ECEI.py used time.shape[0] > 0 and
    # returned np.array([]) when empty.
    if time is not None and len(time) > 0:
        time_ds = time[::decimation_factor]
    else:
        time_ds = time

    return sig_ds, time_ds


# ---------------------------------------------------------------------------
# Z-score spike removal: dual-path (Numba JIT / pure Python)
# ---------------------------------------------------------------------------

def _zscore_core_python(data, shift, start_index, window, threshold):
    """
    Pure-Python inner loop for causal rolling-window Z-score spike removal.
    Modifies data in-place and returns the number of replaced samples.
    """
    n_points = len(data)
    n_replaced = 0

    initial_window = data[start_index - window : start_index] - shift
    mean_old = np.mean(initial_window)
    var_old = np.var(initial_window)

    for i in range(start_index, n_points):
        # Update rolling stats before check (skip first iteration to avoid double-count).
        # Matches ECEI_local: add data[i-1] (last checked), remove data[i-window].
        if i > start_index:
            value_entering = data[i - 1] - shift
            oldest_val = data[i - window] - shift
            mean_new = mean_old + (value_entering - oldest_val) / window
            var_new = var_old + mean_old**2 - mean_new**2 + \
                      (value_entering**2 - oldest_val**2) / window
            if var_new < 0:
                var_new = 0.0
            mean_old = mean_new
            var_old = var_new

        std_dev = var_old ** 0.5
        z_score = abs(data[i] - shift - mean_old) / (std_dev + 1e-8)
        if z_score > threshold:
            data[i] = data[i - 1]
            n_replaced += 1

    return n_replaced


if HAS_NUMBA:
    @njit
    def _zscore_core_numba(data, shift, start_index, window, threshold):
        """
        Numba JIT inner loop for causal rolling-window Z-score spike removal.
        Same algorithm as _zscore_core_python. Modifies data in-place,
        returns n_replaced.
        """
        n_points = len(data)
        n_replaced = 0

        mean_old = 0.0
        var_old = 0.0
        for k in range(start_index - window, start_index):
            mean_old += (data[k] - shift)
        mean_old /= window
        for k in range(start_index - window, start_index):
            var_old += (data[k] - shift - mean_old) ** 2
        var_old /= window

        for i in range(start_index, n_points):
            # Update rolling stats before check (skip first iteration to avoid double-count).
            # Matches ECEI_local: add data[i-1] (last checked), remove data[i-window].
            if i > start_index:
                value_entering = data[i - 1] - shift
                oldest_val = data[i - window] - shift
                mean_new = mean_old + (value_entering - oldest_val) / window
                var_new = var_old + mean_old**2 - mean_new**2 + \
                          (value_entering**2 - oldest_val**2) / window
                if var_new < 0:
                    var_new = 0.0
                mean_old = mean_new
                var_old = var_new

            std_dev = var_old ** 0.5
            z_score = abs(data[i] - shift - mean_old) / (std_dev + 1e-8)
            if z_score > threshold:
                data[i] = data[i - 1]
                n_replaced += 1

        return n_replaced


def remove_spikes_custom_Z(data, dt, threshold=3, window=50, warmup_seconds=0.05):
    """
    Removes outliers using a strictly causal rolling window Z-score.
    Modifies data in-place. Uses Numba JIT when available.

    Args:
        data (np.array): The signal array (modified in-place!).
        dt (float): Time step in seconds.
        threshold (float): Z-score limit.
        window (int): Number of points in the rolling history.
        warmup_seconds (float): Initial time to skip before processing (default 50ms).
    """
    n_points = len(data)

    start_index = int(warmup_seconds / dt)

    if start_index < window:
        start_index = window
    if start_index >= n_points:
        print(f"Debug: Data length ({n_points}) shorter than warmup ({start_index}). Skipping.")
        return

    shift = np.min(data)

    if HAS_NUMBA:
        _zscore_core_numba(data, shift, start_index, window, float(threshold))
    else:
        _zscore_core_python(data, shift, start_index, window, threshold)


def remove_spikes_custom_Z_count(data, dt, threshold=3, window=50, warmup_seconds=0.05):
    """
    Same as remove_spikes_custom_Z but operates on a copy and returns
    (cleaned_data, n_replaced).
    """
    cleaned = data.copy()
    n_points = len(cleaned)

    start_index = int(warmup_seconds / dt)

    if start_index < window:
        start_index = window
    if start_index >= n_points:
        return cleaned, 0

    shift = np.min(cleaned)

    if HAS_NUMBA:
        n_replaced = _zscore_core_numba(cleaned, shift, start_index, window, float(threshold))
    else:
        n_replaced = _zscore_core_python(cleaned, shift, start_index, window, threshold)

    return cleaned, n_replaced
