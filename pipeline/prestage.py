"""
Parallel pre-stage for ECEI shot data.

Downloads PTDATA archive files from Pelican CDN in parallel so the
toksearch pipeline can read from local disk (PTDATA_LOC=0) with parallel
channel extraction instead of 40+ sequential remote XRootD fetches.

Benchmark findings (shot 142170 on Polaris):
  - All 40 ECEI channels are in ONE 1.2 GB archive (.EIL file)
  - Raw xrdcp: 12.9s at 93 MB/s (network is fast)
  - ptdata64 per channel: ~5s (bottleneck is C ext, not network)
  - 40 sequential remote: 191s, 40 sequential local: 207s
  - Parallel local (8 workers × 5 ch): ~25-30s projected

Strategy:
  1. Download archive files to /tmp via pyxrootd subprocess
  2. Use concurrent.futures.ThreadPoolExecutor inside each Ray worker
     to read multiple channels from the local file simultaneously

Usage:
    from prestage import ShotPreStager, parallel_fetch_channels

    stager = ShotPreStager(channels=ALL_ECEI_CHANNELS)
    stager.prestage_shots([142170, 142171])
    # In Ray worker:
    rec_data = parallel_fetch_channels(shot, channels, stager)
"""

import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path


_INDEX_BASE = os.environ.get(
    "PTDATA_JSON_INDEX_DIR",
    "pelican://osg-htc.org:443/fdp-d3d/archives/index/json/json_indexes_2026-01-13_12:22:11",
)

_DEFAULT_CACHE = Path(os.environ.get(
    "FDP_LOCAL_CACHE",
    f"/tmp/fdp_prestage_{os.environ.get('USER', 'unknown')}",
))


class ShotPreStager:
    """Pre-stage PTDATA archive files for a list of shots."""

    def __init__(self, channels, cache_dir=None, max_concurrent=8, python_bin=None):
        self.channels = channels
        self.cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE
        self.max_concurrent = max_concurrent
        self.python_bin = python_bin or sys.executable
        self._index_cache = {}

    def prestage_shots(self, shots, quiet=False):
        """Download all archive files needed for the given shots.

        Returns dict mapping shot -> {"exts": {ext: local_path}, "elapsed_s": float}
        or shot -> {"error": str} on failure.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        work = []
        for shot in shots:
            work.append(shot)

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_concurrent) as pool:
            futures = {pool.submit(self._prestage_one, shot): shot for shot in work}
            for fut in concurrent.futures.as_completed(futures):
                shot = futures[fut]
                try:
                    results[shot] = fut.result()
                except Exception as e:
                    results[shot] = {"error": str(e)}
                    if not quiet:
                        print(f"  [prestage] shot {shot} FAILED: {e}", flush=True)

        elapsed = time.time() - t0
        n_ok = sum(1 for r in results.values() if "exts" in r)
        total_bytes = sum(
            r.get("bytes", 0) for r in results.values() if "exts" in r
        )

        if not quiet:
            print(f"  [prestage] {n_ok}/{len(shots)} shots staged in {elapsed:.1f}s "
                  f"({total_bytes / 1e6:.1f} MB)", flush=True)

        return results

    def _prestage_one(self, shot):
        """Download archive files for a single shot."""
        idx = self._read_index(shot)
        ext_map = idx.get("pointname_ext", {})
        loc_map = idx.get("ext_location", {})

        needed_exts = {}
        for ch in self.channels:
            ext = ext_map.get(ch)
            if ext and ext not in needed_exts:
                url = loc_map.get(ext)
                if url:
                    needed_exts[ext] = url

        if not needed_exts:
            return {"exts": {}, "bytes": 0, "elapsed_s": 0, "cached": True}

        all_cached = True
        for ext in needed_exts:
            if not (self.cache_dir / f"{shot}{ext}").exists():
                all_cached = False
                break

        if all_cached:
            total_bytes = sum(
                (self.cache_dir / f"{shot}{ext}").stat().st_size
                for ext in needed_exts
            )
            return {
                "exts": {ext: str(self.cache_dir / f"{shot}{ext}") for ext in needed_exts},
                "bytes": total_bytes, "elapsed_s": 0, "cached": True,
            }

        t0 = time.time()
        result = self._download_shot_archives(shot, needed_exts)
        result["elapsed_s"] = time.time() - t0
        result["cached"] = False
        return result

    def _read_index(self, shot):
        if shot in self._index_cache:
            return self._index_cache[shot]

        meta_path = self.cache_dir / f"{shot}.idx.json"
        if meta_path.exists():
            idx = json.loads(meta_path.read_text())
            self._index_cache[shot] = idx
            return idx

        shot_dir = str(shot // 100)
        idx_url = f"{_INDEX_BASE}/{shot_dir}/{shot}.json"

        proc = subprocess.run(
            [self.python_bin, "-c",
             f"import json, os; os._exit(0) if False else None\n"
             f"from pyxrootd import client\n"
             f"f = client.File()\n"
             f"s, _ = f.open('{idx_url}')\n"
             f"assert s['ok'], f'open: {{s}}'\n"
             f"s, data = f.read()\n"
             f"assert s['ok'], f'read: {{s}}'\n"
             f"f.close()\n"
             f"import sys; sys.stdout.buffer.write(data)\n"],
            capture_output=True, timeout=60,
        )
        if not proc.stdout:
            raise RuntimeError(
                f"Index read failed for shot {shot}: "
                f"rc={proc.returncode} stderr={proc.stderr.decode()[:200]}"
            )

        idx = json.loads(proc.stdout)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(idx))
        self._index_cache[shot] = idx
        return idx

    def _download_shot_archives(self, shot, ext_url_map):
        """Download multiple archive files for one shot via subprocess."""
        download_script = _DOWNLOAD_SCRIPT_TEMPLATE.format(
            shot=shot,
            ext_urls=json.dumps(ext_url_map),
            cache_dir=str(self.cache_dir),
        )
        proc = subprocess.run(
            [self.python_bin, "-c", download_script],
            capture_output=True, text=True, timeout=300,
        )
        stdout = proc.stdout.strip()
        if not stdout:
            raise RuntimeError(
                f"Download failed for shot {shot}: "
                f"rc={proc.returncode} stderr={proc.stderr[:300]}"
            )

        info = json.loads(stdout)
        if "error" in info:
            raise RuntimeError(info["error"])
        return info

    def get_env_overrides(self):
        """Return env var dict for local-mode ptdata."""
        return {
            "PTDATA_LOC": "0",
            "SYS_D3": str(self.cache_dir),
        }


_DOWNLOAD_SCRIPT_TEMPLATE = """
import json, os, sys
from pathlib import Path
from pyxrootd import client

shot = {shot}
ext_urls = json.loads('''{ext_urls}''')
cache_dir = Path("{cache_dir}")
cache_dir.mkdir(parents=True, exist_ok=True)

total_bytes = 0
exts = {{}}
for ext, url in ext_urls.items():
    dest = cache_dir / f"{{shot}}{{ext}}"
    if dest.exists():
        exts[ext] = str(dest)
        total_bytes += dest.stat().st_size
        continue
    f = client.File()
    s, _ = f.open(url)
    if not s["ok"]:
        print(json.dumps({{"error": f"open {{url}}: {{s}}"}}))
        os._exit(1)
    s, data = f.read()
    if not s["ok"]:
        print(json.dumps({{"error": f"read {{url}}: {{s}}"}}))
        os._exit(1)
    f.close()
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.rename(dest)
    exts[ext] = str(dest)
    total_bytes += len(data)

print(json.dumps({{"exts": exts, "bytes": total_bytes}}))
os._exit(0)
"""


# ── Parallel channel fetch inside Ray workers ─────────────────────────────────

def _fetch_one_channel(chan, shot, ext, cache_dir):
    """Fetch a single channel from a local PTDATA archive.

    Runs in a thread — ptdata64 C extension releases the GIL during I/O.
    """
    saved = {}
    overrides = {"PTDATA_LOC": "0", "SYS_D3": cache_dir}
    for k, v in overrides.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    unset = ["PTDATA_JSON_INDEX_DIR", "PTDATA_PLUGIN_LIB"]
    for k in unset:
        saved[k] = os.environ.pop(k, None)
    try:
        from ptdata import PtDataFetcher
        fetcher = PtDataFetcher(chan, shot, ext=ext)
        return chan, fetcher.fetch(fetch_times=True)
    except Exception as e:
        return chan, None
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def parallel_fetch_channels(shot, channels, stager, max_threads=8):
    """Fetch multiple channels in parallel from pre-staged local files.

    Returns dict mapping channel_name -> fetch_result (or None on failure).
    Uses ThreadPoolExecutor — ptdata64 releases the GIL for filesystem I/O
    so threads give genuine parallelism for the C extension.
    """
    idx = stager._read_index(shot)
    ext_map = idx.get("pointname_ext", {})
    cache_dir = str(stager.cache_dir)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as pool:
        futures = {}
        for chan in channels:
            ext = ext_map.get(chan)
            if ext is None:
                results[chan] = None
                continue
            fut = pool.submit(_fetch_one_channel, chan, shot, ext, cache_dir)
            futures[fut] = chan

        for fut in concurrent.futures.as_completed(futures):
            chan, data = fut.result()
            results[chan] = data

    return results
