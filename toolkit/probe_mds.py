#!/usr/bin/env python3
"""One-shot probe: which MDSplus nodes return data for a shot? Read-only, prints one line per node.

    fdp run --device d3d python probe_mds.py SHOT TREE NODE [NODE ...]
    fdp run --device d3d python probe_mds.py 185000 IONS "CER.CERQUICK.TANGENTIAL.CHANNEL01:TEMP"

Use it to find the exact node paths before writing a signal spec. Allowed on a login node as a single-shot probe;
loops over many shots belong in a PBS job.
"""
import sys
import time

import numpy as np
from toksearch import MdsSignal, Pipeline

shot, tree, nodes = int(sys.argv[1]), sys.argv[2], sys.argv[3:]
for node in nodes:
    t0 = time.time()
    pipe = Pipeline([shot])
    pipe.fetch("x", MdsSignal(node, tree, dims=("times",)))
    rec = pipe.compute_serial()[0]
    if "x" in rec.errors:
        e = rec.errors["x"]
        tb = e.get("traceback", str(e)) if isinstance(e, dict) else str(e)
        print("FAIL {} {} {}: {}".format(shot, tree, node, str(tb).strip().splitlines()[-1][:200]), flush=True)
    else:
        d = np.asarray(rec["x"]["data"])
        t = np.asarray(rec["x"].get("times", []))
        print("ok   {} {} {}: data {} {} times {} ({:.1f} s)".format(shot, tree, node, d.dtype, d.shape, t.shape,
              time.time() - t0), flush=True)
