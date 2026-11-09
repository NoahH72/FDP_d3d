"""FDP end-to-end smoke test: one PTDATA and two MDSplus fetches for one shot.

Works in both the new env (fdp-2026-10) and the old one (fdp/), and on login or
compute nodes. Always launch through `fdp run`, which sets the tree paths and
the bearer token:

    fdp run --device d3d python fdp_smoke.py [SHOT]        # new env
    fdp run python fdp_smoke.py [SHOT]                     # old env

Prints one line per signal and exits non-zero if any fetch failed.
"""
import base64
import json
import os
import sys
import time

# The old fdp package hard-codes a PTDATA index snapshot that was removed from
# the origin; repoint it the same way ECEI-Data does. The new env never sets it.
STALE_SNAPSHOT = "json_indexes_2026-01-13_12:22:11"
idx = os.environ.get("PTDATA_JSON_INDEX_DIR", "")
if STALE_SNAPSHOT in idx:
    snap = os.environ.get("FDP_INDEX_SNAPSHOT")
    if not snap:
        with open(os.path.expanduser("~/.fdp/latest_index_snapshot")) as f:
            snap = f.read().strip()
    os.environ["PTDATA_JSON_INDEX_DIR"] = idx.replace(STALE_SNAPSHOT, snap)

from toksearch import MdsSignal, Pipeline
from toksearch_d3d import PtDataSignal

shot = int(sys.argv[1]) if len(sys.argv) > 1 else 165920

tok = os.environ.get("BEARER_TOKEN", "")
try:
    p = tok.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    left_h = (claims["exp"] - time.time()) / 3600
    print(f"token: scope={claims.get('scope')!r} hours_left={left_h:.1f}")
except (IndexError, ValueError, KeyError):
    print("token: none or not a JWT")
print("host:", os.uname().nodename, "| proxy:", os.environ.get("ALL_PROXY") or os.environ.get("https_proxy") or "none")

signals = {
    "ptdata_ip": PtDataSignal("ip"),
    "mds_efit01_ipmhd": MdsSignal(r"\ipmhd", "EFIT01"),
    "mds_electrons_ts_core_te": MdsSignal("TS.BLESSED.CORE:TEMP", "ELECTRONS", dims=("times",)),
}
pipe = Pipeline([shot])
for name, sig in signals.items():
    pipe.fetch(name, sig)

t0 = time.time()
rec = pipe.compute_serial()[0]
print(f"shot {shot} fetched in {time.time() - t0:.1f} s")

failed = False
for name in signals:
    if name in rec.errors:
        failed = True
        err = rec.errors[name]
        msg = err.get("traceback", str(err)).strip().splitlines()[-1] if isinstance(err, dict) else str(err)
        print(f"  FAIL {name}: {msg[:200]}")
    else:
        print(f"  ok   {name}: shape {getattr(rec[name]['data'], 'shape', '?')}")
sys.exit(1 if failed else 0)
