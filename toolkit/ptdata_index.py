"""Read the PTDATA json index for one shot from a pinned snapshot, over Pelican (read-only).

FDP raises the same exception for an absent pointname, a shot with no PTDATA and a short outage, so the index is
the only reliable way to tell "absent" from "error". The index file lists every pointname the archive holds for
the shot, with its archive extension:   {"pointname_ext": {"ip": "PLA", "MPI66M067D": "MAG", ...}, ...}

    from ptdata_index import read_index
    idx = read_index(185000)            # dict, raises IndexReadError on failure
    names = idx["pointname_ext"]

The snapshot comes from $FDP_INDEX_SNAPSHOT (set it in sites/site.env), else ~/.fdp/latest_index_snapshot.
Reads go through pyxrootd in a subprocess (the method the production BES/ECEI/Mirnov fetchers use); the token and
proxy come from the environment `fdp run` sets up. Results are cached per process.
"""
import json
import os
import subprocess
import sys

INDEX_BASE = "pelican://osg-htc.org:443/fdp-d3d/archives/index/json"
STALE = ("json_indexes_2026-01-13_12:22:11",)  # removed from the origin; every read through it fails
_CACHE = {}


class IndexReadError(RuntimeError):
    pass


def snapshot():
    snap = os.environ.get("FDP_INDEX_SNAPSHOT")
    if not snap:
        with open(os.path.expanduser("~/.fdp/latest_index_snapshot")) as f:
            snap = f.read().strip()
    if snap in STALE:
        raise IndexReadError("index snapshot {} was removed from the origin; pin a current one".format(snap))
    return snap


def pin_ptdata_env():
    """Point ptdata (old env) at the pinned snapshot. The old fdp package hard-codes a removed snapshot, which
    makes every read fail with 'PtDataError 7: Invalid shot number'. Call before the first fetch."""
    os.environ["PTDATA_JSON_INDEX_DIR"] = "{}/{}".format(INDEX_BASE, snapshot())
    return os.environ["PTDATA_JSON_INDEX_DIR"]


_READER = r"""
import sys
from pyxrootd import client
f = client.File()
s, _ = f.open(sys.argv[1])
if not s['ok']:
    sys.stderr.write('open: %s' % s); sys.exit(2)
s, data = f.read()
if not s['ok']:
    sys.stderr.write('read: %s' % s); sys.exit(3)
f.close()
sys.stdout.buffer.write(data)
"""


def url(shot):
    return "{}/{}/{}/{}.json".format(INDEX_BASE, snapshot(), shot // 100, shot)


def read_index(shot, timeout=60):
    if shot in _CACHE:
        return _CACHE[shot]
    p = subprocess.run([sys.executable, "-c", _READER, url(shot)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout)
    if p.returncode != 0 or not p.stdout:
        raise IndexReadError("index read failed for shot {} (rc={}): {}".format(shot, p.returncode,
                                                                               p.stderr.decode("utf-8", "replace")[-300:]))
    idx = json.loads(p.stdout)
    _CACHE[shot] = idx
    return idx


if __name__ == "__main__":  # fdp run python ptdata_index.py SHOT [REGEX]   (a one-shot probe)
    import re
    shot = int(sys.argv[1])
    names = sorted(read_index(shot).get("pointname_ext", {}))
    if len(sys.argv) > 2:
        names = [n for n in names if re.search(sys.argv[2], n)]
    print("shot {} snapshot {}: {} pointnames".format(shot, snapshot(), len(names)))
    print(" ".join(names[:400]))
