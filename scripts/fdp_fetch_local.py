#!/usr/bin/env python
"""
Workaround for XrdPosix thread-limit crash on Polaris login nodes.

The Polaris login node cgroup limits PIDs to 128, and Cursor's Node.js
processes typically consume ~95.  XRootD's XrdPosix layer (used by
ptdata64_) needs ~20+ threads for its Poller/JobMgr/curl workers,
exceeding the budget.

This script splits the work into two phases:
  Phase 1: download shot file via a standalone helper process that uses
            pyxrootd (XrdCl, no Poller).  The helper exits cleanly via
            os._exit so its XRD threads are reclaimed.
  Phase 2: run ptdata in local mode (PTDATA_LOC=0, SYS_D3=cache dir)
            so the Fortran code reads from the filesystem.

Usage:
    # Set FDP env vars first (exports shown in POLARIS_FDP_STATUS.md)
    python fdp_fetch_local.py            # default: IP 165920
    python fdp_fetch_local.py IP 165920  # specific pointname/shot

    # Download-only mode (phase 1 helper, called by the main process):
    python fdp_fetch_local.py --download IP 165920
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CACHE_DIR = Path(os.environ.get(
    "FDP_LOCAL_CACHE",
    "/tmp/fdp_cache_" + os.environ.get("USER", "unknown"),
))

INDEX_BASE = os.environ.get(
    "PTDATA_JSON_INDEX_DIR",
    "pelican://osg-htc.org:443/fdp-d3d/archives/index/json/json_indexes_2026-01-13_12:22:11",
)


# ──────────────────── Phase 1: download helper ────────────────────

def _do_download(shot: int, pointname: str):
    """Runs inside the helper subprocess.  Prints JSON result to stdout."""
    from pyxrootd import client  # imported only in subprocess

    def xrd_read(url):
        f = client.File()
        s, _ = f.open(url)
        if not s["ok"]:
            raise RuntimeError(f"open {url}: {s}")
        s, data = f.read()
        if not s["ok"]:
            raise RuntimeError(f"read {url}: {s}")
        return data

    shot_dir = str(shot // 100)
    idx_url = f"{INDEX_BASE}/{shot_dir}/{shot}.json"
    idx = json.loads(xrd_read(idx_url))

    ext = idx["pointname_ext"].get(pointname)
    if ext is None:
        avail = list(idx["pointname_ext"].keys())[:20]
        print(json.dumps({"error": f"Pointname '{pointname}' not found. Available: {avail}"}))
        os._exit(1)

    remote_url = idx["ext_location"].get(ext)
    local_path = CACHE_DIR / f"{shot}{ext}"

    if local_path.exists():
        print(json.dumps({"path": str(local_path), "ext": ext, "cached": True}))
        os._exit(0)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = xrd_read(remote_url)
    tmp = local_path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.rename(local_path)
    print(json.dumps({"path": str(local_path), "ext": ext, "cached": False, "bytes": len(data)}))
    os._exit(0)


def _check_cache(shot: int, pointname: str):
    """Quick local check without any XRD import.  Returns (path, ext) or None."""
    meta = CACHE_DIR / f"{shot}.meta.json"
    if meta.exists():
        info = json.loads(meta.read_text())
        ext = info.get("pointname_ext", {}).get(pointname)
        if ext:
            local_path = CACHE_DIR / f"{shot}{ext}"
            if local_path.exists():
                return str(local_path), ext
    return None


def _save_meta(shot: int, idx: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    meta = CACHE_DIR / f"{shot}.meta.json"
    meta.write_text(json.dumps({
        "pointname_ext": idx.get("pointname_ext", {}),
    }))


def ensure_shot_file(shot: int, pointname: str):
    """Download shot file if not cached.  Returns (local_path, ext)."""
    hit = _check_cache(shot, pointname)
    if hit:
        print(f"  cached: {hit[0]}", flush=True)
        return hit

    proc = subprocess.run(
        [sys.executable, __file__, "--download", pointname, str(shot)],
        capture_output=True, text=True,
    )
    # Treat SIGSEGV on exit as OK if stdout contains valid JSON
    stdout = proc.stdout.strip()
    if not stdout:
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"Download subprocess failed (exit {proc.returncode})")

    info = json.loads(stdout)
    if "error" in info:
        raise RuntimeError(info["error"])

    if info.get("cached"):
        print(f"  cached: {info['path']}", flush=True)
    else:
        mb = info.get("bytes", 0) / 1e6
        print(f"  downloaded: {info['path']} ({mb:.1f} MB)", flush=True)

    # Save metadata so future calls skip the subprocess entirely
    _save_meta(shot, {"pointname_ext": {pointname: info["ext"]}})

    return info["path"], info["ext"]


# ──────────────────── Phase 2: local ptdata ────────────────────

def fetch_ptdata_local(pointname: str, shot: int):
    """Download (if needed) and fetch ptdata for a pointname/shot."""
    print(f"Ensuring shot file for {pointname} / {shot}...", flush=True)
    local_path_str, ext = ensure_shot_file(shot, pointname)
    cache_dir = str(Path(local_path_str).parent)

    saved = {}
    overrides = {"PTDATA_LOC": "0", "SYS_D3": cache_dir}
    for k, v in overrides.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v

    # Unset remote-mode vars so XrdPosix doesn't initialize
    remote_vars = ["PTDATA_JSON_INDEX_DIR", "PTDATA_PLUGIN_LIB", "XRD_PLUGINCONFDIR"]
    for rv in remote_vars:
        saved[rv] = os.environ.pop(rv, None)

    try:
        from ptdata import PtDataFetcher
        fetcher = PtDataFetcher(pointname, shot, ext=ext)
        return fetcher.fetch(fetch_times=True)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ──────────────────── CLI ────────────────────

def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--download":
        pointname = sys.argv[2]
        shot = int(sys.argv[3])
        _do_download(shot, pointname)
        return

    if len(sys.argv) >= 3:
        pointname = sys.argv[1]
        shot = int(sys.argv[2])
    else:
        pointname = "IP"
        shot = 165920

    print(f"fdp_fetch_local: pointname={pointname}, shot={shot}", flush=True)
    result = fetch_ptdata_local(pointname, shot)

    print(f"\nData shape:  {result['data'].shape}", flush=True)
    if "times" in result:
        print(f"Times shape: {result['times'].shape}", flush=True)
    print("SUCCESS", flush=True)


if __name__ == "__main__":
    main()
