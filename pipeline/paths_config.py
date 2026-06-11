"""
Central path configuration for the ECEI pipeline.
Set the FDP_DATA_ROOT environment variable to your Eagle project base path, or
edit USER_BASE directly. All other paths are derived from USER_BASE.

Example:
    export FDP_DATA_ROOT=/eagle/MY_PROJECT/MY_USERNAME
"""
import os

import numpy as np

# Polaris (Eagle): data and outputs live under this tree.
# Set FDP_DATA_ROOT env var or edit this line directly for your allocation.
USER_BASE = os.environ.get("FDP_DATA_ROOT", "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>")

# Shot lists (input)
shot_lists_dir = os.path.join(USER_BASE, 'shot_lists')
# Plasma-only shot catalog (CSV with header: shot,shot_type,time_of_shot).
# Previous value pointed at the disruption-labeled whitespace list
# `shot_lists/Current_labeled_dset_highest_tol.txt`; swap back there if you
# need the disruption dataset. All pipeline code loads this via
# `load_clean_shot_list()` below so both formats work.
clean_shots_file = os.path.join(
    USER_BASE, 'pedestal-predictor-onnx', 'data', 'plasma_shots_only.csv'
)
# Legacy whitespace-formatted disruption list (kept for reference / rollback).
disruption_shots_file = os.path.join(shot_lists_dir, 'Current_labeled_dset_highest_tol.txt')
t_end_file = os.path.join(shot_lists_dir, 't_end.txt')


def load_clean_shot_list(path=None):
    """Load shot numbers from `path` (defaults to `clean_shots_file`).

    Supports two layouts:
      * CSV with a header row whose first column is the shot number
        (e.g. `plasma_shots_only.csv` -> header `shot,shot_type,time_of_shot`).
      * Whitespace-separated numeric text with shot in column 0
        (e.g. `Current_labeled_dset_highest_tol.txt` -> `shot  t_disrupt`).

    Returns a 1-D numpy int array of shot numbers (caller does its own slicing).
    """
    path = path or clean_shots_file
    if path.lower().endswith('.csv'):
        return np.loadtxt(path, delimiter=',', skiprows=1, usecols=0, dtype=int)
    data = np.loadtxt(path)
    if data.ndim == 1:
        return data.astype(int)
    return data[:, 0].astype(int)

# Signal data (output)
signal_data_dir = os.path.join(USER_BASE, 'signal_data')
ecei_output_dir = os.path.join(signal_data_dir, 'ECEI_MHz')
phys_output_dir = os.path.join(signal_data_dir, 'Physics_Raw')
ecei_assembled_dir = os.path.join(signal_data_dir, 'ECEI_Assembled')
ecei_assembled_test_dir = os.path.join(signal_data_dir, 'ECEI_Assembled_Test')
ecei_local_reference_dir = os.path.join(signal_data_dir, 'ECEI_local_Reference')
qa_report_file = os.path.join(signal_data_dir, 'ECEI_QA_Report.txt')
diagnostic_report_file = os.path.join(signal_data_dir, 'ECEI_Diagnostic_Report.md')
last_run_file = os.path.join(signal_data_dir, 'last_run.json')

# fetchrawdata_local.py (raw data workflow)
MANIFEST_FILE = os.path.join(USER_BASE, 'd3d_signal_manifest_full.csv')
OUTPUT_ROOT = os.path.join(USER_BASE, 'd3d_raw_data_hdf5')
STATS_INDEX_FILE = os.path.join(USER_BASE, 'd3d_raw_data_stats.csv')

# Physics raw (sharded layout, matches rodriguezj)
phys_raw_root = os.path.join(signal_data_dir, 'd3d_raw_data_hdf5')
# rodriguezj's shared store on Polaris/Eagle (read-only target; never append in place).
RODRIGUEZJ_PHYS_SOURCE = os.environ.get("RODRIGUEZJ_PHYS_SOURCE", "")
# saga7 beegfs path kept for reference (works only from saga, not Polaris).
RODRIGUEZJ_PHYS_SOURCE_SAGA = '/mnt/beegfs/users/rodriguezj/d3d_raw_data_hdf5'
