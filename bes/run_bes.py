#!/usr/bin/env python3
"""
Entry point for the standalone BES fetch on Polaris (or any other host).

Reads a shot list from a CSV/text file, slices it by BATCH_START/BATCH_END,
and calls bes_fetch.fetch_bes() to write each shot's HDF5 under BES_RAW_ROOT.

This script has only stdlib + bes_fetch (which itself only needs numpy, h5py,
toksearch). It does NOT import the saga ECEI-Data modules (physics_config,
physics_io, paths_config, run_physics_download, resource_utils).

Required environment:
    SHOT_LIST      Path to CSV/text file. CSV: prefers a 'shot' column,
                   falls back to the first column. Text: first integer per line.
    BES_RAW_ROOT   Output root (sharded: {root}/{shot//1000}xxx/{shot}.h5)

Optional environment:
    BATCH_START=0            first index into the shot list (default 0)
    BATCH_END                one past last index (default: end of list)
    BES_WORKERS=8            Ray worker count for the channel-extraction stage
    REQUIRE_FULL=1           only skip shots with all 64 channels already present
                             (default: skip if any BES + timebase present)
    BES_PRESTAGE=1           Pre-download .BES archives via xrdcp and extract
                             channels locally in parallel (default ON on
                             Polaris; gives ~5-7x speedup over direct remote
                             PtDataSignal fetches). Set BES_PRESTAGE=0 to
                             disable.
    BES_SHOT_BATCH=50        Shots per prestage+pipeline batch (only used when
                             prestaging).
    BES_PRESTAGE_CONCURRENCY=8   xrdcp concurrency for prestage step.
    BES_FETCH_THREADS=8      Per-worker thread count for parallel local
                             channel extraction (only used when prestaging).

Example:
    SHOT_LIST=/eagle/MY_PROJECT/MY_USERNAME/plasma_shots.csv \
    BES_RAW_ROOT=/eagle/MY_PROJECT/MY_USERNAME/signal_data/BES_Raw \
    BATCH_START=0 BATCH_END=200 BES_WORKERS=8 \
    python run_bes.py
"""

from __future__ import annotations

import csv
import os
import sys

import bes_fetch


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def load_shots(path: str):
    """Load shot numbers from a CSV (preferred) or whitespace-separated text file.

    CSV: looks for a 'shot' column header; otherwise uses the first column.
    Text: takes the first integer-parseable token on each non-empty line.
    """
    shots = []
    with open(path, "r") as f:
        sample = f.read(4096)
        f.seek(0)
        if "," in sample:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                col = "shot" if "shot" in reader.fieldnames else reader.fieldnames[0]
                for row in reader:
                    try:
                        shots.append(int(row[col]))
                    except (TypeError, ValueError):
                        continue
            else:
                f.seek(0)
                for line in f:
                    tok = line.strip().split(",")
                    if not tok:
                        continue
                    try:
                        shots.append(int(tok[0]))
                    except ValueError:
                        continue
        else:
            for line in f:
                tok = line.strip().split()
                if not tok:
                    continue
                try:
                    shots.append(int(tok[0]))
                except ValueError:
                    continue
    return shots


def main():
    shot_list_path = os.environ.get("SHOT_LIST")
    if not shot_list_path:
        print("ERROR: set SHOT_LIST=/path/to/shots.csv (or .txt)", file=sys.stderr)
        sys.exit(2)
    if not os.path.exists(shot_list_path):
        print("ERROR: SHOT_LIST does not exist: {}".format(shot_list_path), file=sys.stderr)
        sys.exit(2)

    root = os.environ.get("BES_RAW_ROOT")
    if not root:
        root = os.path.join(os.getcwd(), "BES_Raw")
        print("WARN: BES_RAW_ROOT unset; defaulting to {}".format(root))

    shots = load_shots(shot_list_path)
    print("Loaded {} shots from {}".format(len(shots), shot_list_path))
    if not shots:
        print("Shot list is empty. Exiting.")
        return

    bs = int(os.environ.get("BATCH_START", 0))
    be_env = os.environ.get("BATCH_END")
    be = int(be_env) if be_env else len(shots)
    sliced = shots[bs:be]
    print("Slicing [{}:{}] -> {} shots".format(bs, be, len(sliced)))
    if not sliced:
        print("Empty slice. Exiting.")
        return

    workers = int(os.environ.get("BES_WORKERS", 8))
    require_full = _env_bool("REQUIRE_FULL", False)
    prestage = _env_bool("BES_PRESTAGE", True)
    shot_batch_size = int(os.environ.get("BES_SHOT_BATCH", 50))
    prestage_concurrency = int(os.environ.get("BES_PRESTAGE_CONCURRENCY", 8))
    fetch_threads = int(os.environ.get("BES_FETCH_THREADS", 8))

    print("Output root:  {}".format(root))
    print("Workers:      {}".format(workers))
    print("require_full: {}".format(require_full))
    print("prestage:     {}  (shot_batch={}, prestage_concurrency={}, fetch_threads={})".format(
        prestage, shot_batch_size, prestage_concurrency, fetch_threads,
    ))
    bes_fetch.fetch_bes(
        sliced,
        root,
        num_workers=workers,
        sharded=True,
        require_full=require_full,
        prestage=prestage,
        shot_batch_size=shot_batch_size,
        prestage_concurrency=prestage_concurrency,
        fetch_threads=fetch_threads,
    )
    print("Done.")


if __name__ == "__main__":
    main()
