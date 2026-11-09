#!/usr/bin/env python3
"""One-shot API probe for the Mirnov fetcher (new env, FDP). Read-only; writes only OUT.json.

  fdp run --device d3d python probe_api.py OUT.json

Shot 185000 (saga reference values exist): for MPI66M067D, B1, MPID66M067 it fetches calibrated (Full) and raw
counts through the same reader toksearch uses, dumps the ExtractedData / header / time-domain attributes, checks the
saga reference hashes, the float32 count-preservation test and whether t0 + i*dt rebuilds the times exactly.
Then: list_pointnames for the shot, and the exception text for the negative controls.
"""
import csv
import hashlib
import json
import os
import sys
import time
import traceback

import numpy as np
import ptdata
from ptdata import _core
from toksearch_d3d.signal.ptdata import PtDataReaderRegistry

ROOT = "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10"


def attrs(obj, depth=0):
    out = {}
    for k in dir(obj):
        if k.startswith("_"):
            continue
        try:
            v = getattr(obj, k)
        except Exception as e:
            out[k] = "<err {}>".format(e)
            continue
        if callable(v):
            out[k] = "<method>"
        elif isinstance(v, (int, float, str, bool)) or v is None:
            out[k] = v
        elif hasattr(v, "__len__") and not isinstance(v, (bytes, str)):
            try:
                a = np.asarray(v)
                out[k] = "<array {} {} first={}>".format(a.dtype, a.shape, a.ravel()[:4].tolist())
            except Exception:
                out[k] = "<seq len {}>".format(len(v))
        elif depth < 2:
            out[k] = attrs(v, depth + 1)
        else:
            out[k] = repr(v)[:200]
    return out


def exc(e):
    return {"type": "{}.{}".format(type(e).__module__, type(e).__name__), "str": str(e),
            "code": repr(getattr(e, "code", None)), "tb": traceback.format_exc()[-800:]}


def fetch(reader, name, shot, mode):
    p = _core.ExtractionParams()
    p.fetch_times = True
    p.calibration = mode
    t0 = time.time()
    r = reader.fetch(name, shot, p)
    return r, time.time() - t0


def float32_test(raw, full):
    raw = np.asarray(raw).astype(np.int64)
    full = np.asarray(full, dtype=np.float64)
    order = np.argsort(raw, kind="stable")
    rs, fs = raw[order], full[order]
    # 1) each raw count maps to exactly one float64 value
    brk = np.flatnonzero(np.diff(rs)) + 1
    groups_r = np.split(rs, brk)
    groups_f = np.split(fs, brk)
    one_to_one = all(np.all(g == g[0]) for g in groups_f)
    counts = np.array([g[0] for g in groups_r])
    vals = np.array([g[0] for g in groups_f])
    # 2) float32 keeps distinct counts distinct, monotone, and rounding << one count step
    v32 = vals.astype(np.float32)
    distinct = np.unique(v32).size == vals.size
    step = np.min(np.abs(np.diff(vals))) if vals.size > 1 else np.nan
    max_err = float(np.max(np.abs(v32.astype(np.float64) - vals))) if vals.size else 0.0
    return {"n_distinct_counts": int(counts.size), "count_min": int(counts.min()), "count_max": int(counts.max()),
            "count_to_value_one_to_one": bool(one_to_one), "float32_keeps_counts_distinct": bool(distinct),
            "min_value_step": float(step), "max_float32_rounding": max_err,
            "rounding_over_step": float(max_err / step) if step and step == step else None,
            "affine_fit": np.polyfit(counts.astype(np.float64), vals, 1).tolist() if counts.size > 1 else None}


def time_test(t):
    t = np.asarray(t, dtype=np.float64)
    n = t.size
    out = {"n": n, "t0": float(t[0]), "t_last": float(t[-1])}
    d = np.diff(t)
    out.update(dt_min=float(d.min()), dt_max=float(d.max()), n_distinct_dt=int(np.unique(d).size))
    i = np.arange(n, dtype=np.float64)
    for label, dt in (("dt_first", float(d[0])), ("dt_mean", float((t[-1] - t[0]) / (n - 1)))):
        rec = t[0] + i * dt
        out["rebuild_" + label] = {"dt": dt, "exact": bool(np.array_equal(rec, t)),
                                   "max_abs_err_ms": float(np.max(np.abs(rec - t)))}
    return out


def main():
    out_path = sys.argv[1]
    ref = {}
    with open(os.path.join(ROOT, "inputs", "reference_values_smoke.csv")) as f:
        for r in csv.DictReader(f):
            ref[(int(r["shot"]), r["pointname"])] = r
    res = {"versions": {}, "env": {k: os.environ.get(k) for k in ("PTDATA_JSON_INDEX_DIR", "SYS_D3", "PTDATA_PTSERVERS",
                                                               "XRD_PLUGINCONFDIR")}}
    for p in ("fdp", "toksearch", "toksearch_d3d", "ptdata", "numpy", "h5py"):
        try:
            from importlib.metadata import version
            res["versions"][p] = version(p)
        except Exception as e:
            res["versions"][p] = str(e)
    reader = PtDataReaderRegistry().reader()
    for k in ("has_index_plugin", "http_endpoints", "ptserver_chain"):
        try:
            v = getattr(reader, k)
            res["reader_" + k] = repr(v() if callable(v) else v)[:500]
        except Exception as e:
            res["reader_" + k] = exc(e)
    shot = 185000
    res["channels"] = {}
    for name in ("MPI66M067D", "B1", "MPID66M067"):
        c = {}
        try:
            full, tf = fetch(reader, name, shot, _core.CalibrationMode.Full)
            raw, tr = fetch(reader, name, shot, _core.CalibrationMode.Raw)
            d = np.asarray(full.data)
            t = np.asarray(full.times)
            ri = np.asarray(raw.raw_integer)
            c["extracted_full"] = attrs(full)
            c["extracted_raw_raw_integer"] = "{} {}".format(ri.dtype, ri.shape)
            c["seconds"] = {"full": round(tf, 2), "raw": round(tr, 2)}
            c["data_dtype"] = str(d.dtype)
            c["sha256_data_float32_le"] = hashlib.sha256(d.astype("<f4").tobytes()).hexdigest()
            c["sha256_times_float64_le"] = hashlib.sha256(t.astype("<f8").tobytes()).hexdigest()
            rr = ref.get((shot, name))
            if rr:
                c["ref_match_data"] = c["sha256_data_float32_le"] == rr["sha256_data_float32_le"]
                c["ref_match_times"] = c["sha256_times_float64_le"] == rr["sha256_times_float64_le"]
                c["ref_n"] = rr["n"]
            c["n"] = int(d.size)
            c["float32_test"] = float32_test(ri, d)
            c["time_test"] = time_test(t)
            try:
                h = reader.read_header(name, shot)
                c["header"] = attrs(h)
            except Exception as e:
                c["header"] = exc(e)
        except Exception as e:
            c["error"] = exc(e)
        res["channels"][name] = c
        print(name, json.dumps({k: c.get(k) for k in ("n", "seconds", "ref_match_data", "ref_match_times",
                                                      "float32_test", "time_test", "error")}, default=str)[:1500],
              flush=True)
    try:
        names = reader.list_pointnames(shot)
        names = [str(x) for x in names]
        res["list_pointnames"] = {"n": len(names), "MPI66M_D": sorted(x for x in names if x.startswith("MPI66M") and x.endswith("D")),
                                  "sample": names[:20]}
    except Exception as e:
        res["list_pointnames"] = exc(e)
    neg = {}
    for label, name, s in (("dbdt absent (saga error 1)", "MPI66M067D", 202640), ("no PTDATA shot (saga error 22)", "ip", 177267),
                           ("bogus pointname", "NOSUCHPT1", 185000), ("canary ip 185000", "ip", 185000)):
        t0 = time.time()
        try:
            r, _ = fetch(reader, name, s, _core.CalibrationMode.Full)
            neg[label] = {"ok": True, "n": len(r.data), "seconds": round(time.time() - t0, 1)}
        except Exception as e:
            neg[label] = dict(exc(e), seconds=round(time.time() - t0, 1))
        print(label, json.dumps(neg[label])[:600], flush=True)
    res["negative"] = neg
    with open(out_path, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
