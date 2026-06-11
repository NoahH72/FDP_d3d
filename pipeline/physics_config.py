"""
Declarative config for physics (MDS + PTDATA) signals.
Used by run_physics_download to build TokSearch signal lists.
Edensfit axis mapping (DIM_OF 0=rho, 1=time) is explicit here.
"""

MDS_LOCATION = "remote://atlas.gat.com"

# --- Edensfit (ZIPFIT01): main node + axis nodes ---
EDENSFIT_TREE = "ZIPFIT01"
EDENSFIT_NODE = "PROFILES.EDENSFIT"
# DIM_OF(..., 0) = rho (normalized radius), DIM_OF(..., 1) = time
EDENSFIT_AXES = {
    "rho": "DIM_OF(PROFILES.EDENSFIT,0)",
    "time": "DIM_OF(PROFILES.EDENSFIT,1)",
}

# --- EFIT (magnetics/geometry) ---
EFIT_TREE = "EFIT01"
EFIT_VARS = {
    "kappa": "RESULTS.AEQDSK.KAPPA",
    "betap": "RESULTS.AEQDSK.BETAP",
    "tribot": "RESULTS.AEQDSK.TRIBOT",
    "tritop": "RESULTS.AEQDSK.TRITOP",
    "rvsin": "RESULTS.AEQDSK.RVSIN",
    "rvsout": "RESULTS.AEQDSK.RVSOUT",
    "zvsin": "RESULTS.AEQDSK.ZVSIN",
    "zvsout": "RESULTS.AEQDSK.ZVSOUT",
    "rmaxis": "RESULTS.AEQDSK.R0",
    "zmaxis": "RESULTS.AEQDSK.Z0",
    "pohm": "RESULTS.AEQDSK.POH",
}

# --- Gas valves (NEUTRALS) ---
GAS_TREE = "NEUTRALS"
GAS_VALVES = ["A", "B", "C", "D", "E"]  # node: GASFLOW.GAS{X}:FLOW

# --- PTDATA signal names (fast / real-time). Key = record key, value = PtData name ---
PTDATA_SIGNALS = [
    ("ip", "IP"),
    ("ipspr15v", "ipspr15V"),
    ("bt", "bt"),
    ("density", "dssdenest"),
    ("li", "efsli"),
    ("prad", "PRAD"),
    ("n1rms", "nssampn1l"),
    ("n2rms", "nssampn2l"),
    ("pinj", "bmspinj"),
    ("tinj", "bmstinj"),
]
BEAM_PORTS = ["15l", "15r", "21l", "21r", "30l", "30r", "33l", "33r"]
PTDATA_BEAM = [(f"pinj_{p}", f"bmspinj{p}") for p in BEAM_PORTS] + [
    (f"tinj_{p}", f"bmstinj{p}") for p in BEAM_PORTS
]
PTDATA_ECH_PELLET = [
    ("ech_total", "ECHPWR"),
    ("pellet_d2", "PPG105D2"),
    ("pellet_ne", "PPG105NE"),
    ("pellet_he", "PPG105HE"),
]
F_COILS = [
    "F1A", "F2A", "F3A", "F4A", "F5A", "F6A", "F7A", "F8A", "F9A",
    "F1B", "F2B", "F3B", "F4B", "F5B", "F6B", "F7B", "F8B", "F9B",
]
E_COILS = ["ECOILA", "ECOILB", "E567UP", "E567DN", "E89DN", "E89UP"]

# --- Fusion-FM additional signals (NOT in advisor fetch; fetch separately and append) ---
# PTDATA: dst/dalpha removed (diagnostic: not available; may add back if point names found)
PTDATA_FUSION_FM_EXTRA = []
# Thomson scattering: MDS tree ELECTRONS, path TOP.TS.BLESSED (DIII-D wiki).
# PTDATA point names: TSTE_CORE, TSNE_CORE, TSTIME_CORE (Reviewplus).
THOMSON_TREE = "ELECTRONS"
# NOTE: TokSearch's MdsSignal (with tree="ELECTRONS") resolves Thomson
# using the relative path without the "TOP." prefix.
THOMSON_TE_NODE = "TS.BLESSED.CORE:TEMP"
THOMSON_NE_NODE = "TS.BLESSED.CORE:DENSITY"
# Legacy names used in HDF5 groups and verification:
MPTS_TREE = THOMSON_TREE
MPTS_TE_NODE = THOMSON_TE_NODE
MPTS_NE_NODE = THOMSON_NE_NODE
# BES: BESFU01 .. BESFU64 (64 channels)
PTDATA_BES = [(f"besfu{i:02d}", f"BESFU{i:02d}") for i in range(1, 65)]
# ECE: ece1..ece40 via PTDATA (same as advisor; MDS TECE not used)
PTDATA_ECE = [(f"ece{i}", f"ece{i}") for i in range(1, 41)]

# MDS: Filterscope (SPECTROSCOPY), CO2 interferometer (BCI), EFIT01 RMIDOUT/WMHD
SPECTROSCOPY_TREE = "SPECTROSCOPY"
# HDF5 group keys used throughout the repo: 'fs00' .. 'fs05'.
# TokSearch's MdsSignal needs backslash-prefixed tag names (e.g. '\FS00')
# rather than plain 'fs00'/'FS00'.
FILTERSCOPE_SIGNAL_MAP = {f"fs{i:02d}": rf"\FS{i:02d}" for i in range(6)}  # fs00..fs05 -> \FS00..\FS05

BCI_TREE = "BCI"
# New format for shots > 195740
BCI_NODES = ["DENr0UF", "DENv1UF", "DENv2UF", "DENv3UF"]
# Legacy segmented format for shots <= 195740 (DENr0_UF_0..9, etc.)
# Set via: python detect_bci_era.py (first shot where new format is OK)
BCI_NEW_FORMAT_SHOT_THRESHOLD = 195741
BCI_LEGACY_BASES = ["DENr0", "DENv1", "DENv2", "DENv3"]
BCI_LEGACY_NODES = [f"{base}_UF_{i}" for base in BCI_LEGACY_BASES for i in range(10)]

# EFIT01 extra nodes (full path required; bare RMIDOUT/WMHD do not resolve)
EFIT_EXTRA_NODES = {"rmidout": "RESULTS.AEQDSK.RMIDOUT", "wmhd": "RESULTS.AEQDSK.WMHD"}

# --- ZIPFIT01 additional profile signals (etempfit / itempfit / trotfit) ---
# Fetched via FDP/Pelican on Polaris compute nodes. Unlike edensfit (which uses
# location="remote://atlas.gat.com" + separate DIM_OF TDI calls), these signals
# use MdsSignal(dims=("rho","times")) which resolves dims via node.getDimensionAt()
# on the Pelican-served MDS tree. DIM_OF(...) TDI expressions do NOT work via
# Pelican; dims= returns {data, rho, times, units} in a single record entry.
#
# Raw ZIPFIT units (kept as-is, per edensfit convention): keV / kHz / ms / -.
# imas_composer applies *1e3 conversions for IMAS physical units; we don't.
ZIPFIT_EXTRAS_TREE = "ZIPFIT01"
ZIPFIT_EXTRA_SPECS = [
    # (hdf5 group key, MDSplus node, dims tuple matching edensfit: dim0=rho, dim1=time)
    ("etempfit", "PROFILES.ETEMPFIT", ("rho", "times")),
    ("itempfit", "PROFILES.ITEMPFIT", ("rho", "times")),
    ("trotfit",  "PROFILES.TROTFIT",  ("rho", "times")),
]


def get_zipfit_extras_signal_list(ts_module):
    """
    MDS signals for ZIPFIT01 etempfit/itempfit/trotfit via FDP/Pelican.

    Uses MdsSignal(..., dims=("rho","times")) so dim arrays come back inside the
    same record entry (keys 'rho' and 'times'); callers should NOT also fetch
    DIM_OF(...) helpers, which fail under Pelican with TreeINVPATH.
    Omitting `location` lets `fdp run` route the fetch through the Pelican tree
    path set in $default_tree_path; works identically on login and compute nodes
    (compute nodes route via $ALL_PROXY to the login-node HTTPS proxy).
    """
    signals = {}
    for key, node, dims in ZIPFIT_EXTRA_SPECS:
        signals[key] = ts_module.MdsSignal(node, ZIPFIT_EXTRAS_TREE, dims=dims)
    return signals


def get_zipfit_extras_signal_names():
    """HDF5 group keys written for the ZIPFIT extras. Must match signal_list keys."""
    return [key for key, _node, _dims in ZIPFIT_EXTRA_SPECS]


def build_signal_list_from_config(skip_ptdata, ts_module, which="all"):
    """
    Build TokSearch signal dict from config.
    which: 'all' | 'slow' | 'fast'
      - slow: MDS only (edensfit + axes, EFIT, gas)
      - fast: PTDATA only
      - all: slow + fast (when not skip_ptdata)
    """
    signals = {}
    loc = MDS_LOCATION

    if which in ("all", "slow"):
        # Edensfit + axis helpers
        signals["edensfit"] = ts_module.MdsSignal(
            EDENSFIT_NODE, EDENSFIT_TREE, location=loc
        )
        signals["edensfit_time"] = ts_module.MdsSignal(
            EDENSFIT_AXES["time"], EDENSFIT_TREE, location=loc
        )
        signals["edensfit_rho"] = ts_module.MdsSignal(
            EDENSFIT_AXES["rho"], EDENSFIT_TREE, location=loc
        )
        # EFIT
        for name, path in EFIT_VARS.items():
            signals[name] = ts_module.MdsSignal(path, EFIT_TREE, location=loc)
        # Gas
        for gas in GAS_VALVES:
            key_name = "gas{}_cal".format(gas.lower())
            node_path = "GASFLOW.GAS{}:FLOW".format(gas)
            signals[key_name] = ts_module.MdsSignal(node_path, GAS_TREE, location=loc)

    if which in ("all", "fast") and not skip_ptdata:
        for key, ptdata_name in PTDATA_SIGNALS:
            signals[key] = ts_module.PtDataSignal(ptdata_name)
        for key, ptdata_name in PTDATA_BEAM:
            signals[key] = ts_module.PtDataSignal(ptdata_name)
        for key, ptdata_name in PTDATA_ECH_PELLET:
            signals[key] = ts_module.PtDataSignal(ptdata_name)
        for coil in F_COILS:
            signals[coil.lower()] = ts_module.PtDataSignal(coil)
        for coil in E_COILS:
            signals[coil.lower()] = ts_module.PtDataSignal(coil)

    return signals


def get_slow_signal_list(ts_module):
    """MDS-only signals (edensfit, EFIT, gas). Small per shot."""
    return build_signal_list_from_config(skip_ptdata=False, ts_module=ts_module, which="slow")


def get_fast_signal_list(ts_module):
    """PTDATA-only signals. Large per shot."""
    return build_signal_list_from_config(skip_ptdata=False, ts_module=ts_module, which="fast")


def get_fusion_fm_additional_signal_list(ts_module):
    """
    Only the Fusion-FM extra signals (dst, dalpha, mpts.te/ne, BES, Filterscope, BCI, ECE, EFIT RMIDOUT/WMHD).
    Use this to fetch and append to existing physics HDF5 from advisor's repo without re-downloading
    ip, bt, density, edensfit, coils, beams, etc.
    """
    signals = {}
    signals.update(get_fusion_fm_ptdata_signal_list(ts_module))
    signals.update(get_fusion_fm_mds_signal_list(ts_module))
    return signals


def get_fusion_fm_ptdata_signal_list(ts_module):
    """PTDATA-only subset of Fusion-FM extras: BES + ECE (and any PTDATA_FUSION_FM_EXTRA)."""
    signals = {}
    for key, ptdata_name in PTDATA_FUSION_FM_EXTRA:
        signals[key] = ts_module.PtDataSignal(ptdata_name)
    for key, ptdata_name in PTDATA_BES:
        signals[key] = ts_module.PtDataSignal(ptdata_name)
    for key, ptdata_name in PTDATA_ECE:
        signals[key] = ts_module.PtDataSignal(ptdata_name)
    return signals


def get_fusion_fm_mds_signal_list(ts_module):
    """MDS-only subset of Fusion-FM extras: BCI, Filterscope, Thomson, EFIT extra."""
    signals = {}
    loc = MDS_LOCATION
    signals["mpts_te"] = ts_module.MdsSignal(MPTS_TE_NODE, MPTS_TREE, location=loc)
    signals["mpts_ne"] = ts_module.MdsSignal(MPTS_NE_NODE, MPTS_TREE, location=loc)
    for key, node_expr in FILTERSCOPE_SIGNAL_MAP.items():
        signals[key] = ts_module.MdsSignal(node_expr, SPECTROSCOPY_TREE, location=loc)
    for node in BCI_NODES:
        signals[node.lower()] = ts_module.MdsSignal(node, BCI_TREE, location=loc)
    for node in BCI_LEGACY_NODES:
        key = node.lower()
        signals[key] = ts_module.MdsSignal(r"\BCI::" + node, BCI_TREE, location=loc)
    for key, node in EFIT_EXTRA_NODES.items():
        signals[key] = ts_module.MdsSignal(node, EFIT_TREE, location=loc)
    return signals


def get_fusion_fm_additional_signal_names():
    """
    Return the list of Fusion-FM extra signal names (no toksearch).
    Must match get_fusion_fm_additional_signal_list(ts).keys() for verification.
    """
    names = [key for key, _ in PTDATA_FUSION_FM_EXTRA]
    names.extend(key for key, _ in PTDATA_BES)
    names.extend(key for key, _ in PTDATA_ECE)
    names.extend(["mpts_te", "mpts_ne"])
    names.extend(FILTERSCOPE_SIGNAL_MAP.keys())
    names.extend(node.lower() for node in BCI_NODES)
    names.extend(node.lower() for node in BCI_LEGACY_NODES)
    names.extend(EFIT_EXTRA_NODES.keys())
    return names
