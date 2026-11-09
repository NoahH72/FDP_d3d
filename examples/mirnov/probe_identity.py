#!/usr/bin/env python3
"""Identity check of the smoke reference channels against saga, for whichever env runs it.

  new env:  fdp run --device d3d python probe_identity.py OUT.json new
  old env:  $FDP_CLI run $FDP_PY probe_identity.py OUT.json old
Read-only. For each (shot, pointname) in inputs/reference_values_smoke.csv: fetch calibrated (ical=1) and raw counts
(ical=0) with PtDataSignal, compare n / t range / dt / min / max / mean / mid value / SHA-256 (data as float32 LE,
times as float64 LE) with saga, and test whether float64 arithmetic on the raw counts with the header constants
(rc_over_g * inherent_number * (count - zero_offset)) reproduces saga's values exactly.
"""
import csv
import hashlib
import json
import os
import sys
import time
import traceback
import warnings

import numpy as np

warnings.simplefilter("ignore")
ROOT = "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10"
STALE = "json_indexes_2026-01-13_12:22:11"


def main():
    out, env = sys.argv[1], sys.argv[2]
    if env == "old":
        idx = os.environ.get("PTDATA_JSON_INDEX_DIR", "")
        snap = os.environ.get("FDP_INDEX_SNAPSHOT") or open(os.path.expanduser("~/.fdp/latest_index_snapshot")).read().strip()
        os.environ["PTDATA_JSON_INDEX_DIR"] = idx.replace(STALE, snap) if STALE in idx else idx
        import toksearch as ts
        PtDataSignal = getattr(ts, "PtDataSignal", None)
        if PtDataSignal is None:
            from toksearch_d3d import PtDataSignal
    else:
        from toksearch_d3d import PtDataSignal
    from importlib.metadata import version
    res = {"env": env, "versions": {p: version(p) for p in ("toksearch", "toksearch_d3d", "ptdata")},
           "PTDATA_JSON_INDEX_DIR": os.environ.get("PTDATA_JSON_INDEX_DIR"), "rows": []}
    for r in csv.DictReader(open(os.path.join(ROOT, "inputs", "reference_values_smoke.csv"))):
        shot, name = int(r["shot"]), r["pointname"]
        row = {"shot": shot, "pointname": name, "saga_status": r["status"]}
        t0 = time.time()
        try:
            g = PtDataSignal(name, keep_header=True).gather(shot)
            d, t = np.asarray(g["data"]), np.asarray(g["times"])
            row["seconds"] = round(time.time() - t0, 2)
            row.update(n=int(d.size), dtype=str(d.dtype), units=str(g.get("units", {}).get("data")))
            if r["status"] == "ok":
                mid = int(r["mid_index"])
                ours = {"n": d.size, "t_first_ms": t[0], "t_last_ms": t[-1], "dt_min_ms": np.diff(t).min(),
                        "dt_max_ms": np.diff(t).max(), "data_min": d.min(), "data_max": d.max(),
                        "data_mean_f64": float(np.mean(d.astype(np.float64))), "data_mid": d[mid]}
                row["match"] = {k: bool(float(ours[k]) == float(r[k])) for k in ours}
                row["rel_diff"] = {k: float(abs(float(ours[k]) - float(r[k])) / max(abs(float(r[k])), 1e-300))
                                   for k in ("data_min", "data_max", "data_mean_f64", "data_mid")}
                row["ratio_mid_ours_over_saga"] = float(d[mid]) / float(r["data_mid"]) if float(r["data_mid"]) else None
                row["sha_data_match"] = hashlib.sha256(d.astype("<f4").tobytes()).hexdigest() == r["sha256_data_float32_le"]
                row["sha_times_match"] = hashlib.sha256(t.astype("<f8").tobytes()).hexdigest() == r["sha256_times_float64_le"]
                row["data_is_float32_exact"] = bool(np.array_equal(d.astype(np.float32).astype(np.float64), d))
                try:
                    raw = np.asarray(PtDataSignal(name, ical=0).gather(shot)["data"]).astype(np.float64)
                    h = g.get("header")
                    rc, inh, zo = float(h.rc_over_g()), float(h.inherent_number()), float(h.zoff())
                    cand = {"rc*inh*(c-zoff)": rc * inh * (raw - zo), "(rc*inh)*(c-zoff)": (rc * inh) * (raw - zo),
                            "rc*(inh*(c-zoff))": rc * (inh * (raw - zo))}
                    row["recompute_f64"] = {}
                    for label, v in cand.items():
                        row["recompute_f64"][label] = {
                            "equals_returned": bool(np.array_equal(v, d)),
                            "mid_equals_saga": bool(float(v[mid]) == float(r["data_mid"])),
                            "min_max_mean_equal_saga": [bool(float(v.min()) == float(r["data_min"])),
                                                        bool(float(v.max()) == float(r["data_max"])),
                                                        bool(float(np.mean(v)) == float(r["data_mean_f64"]))]}
                    row["header"] = {"rc_over_g": rc, "inherent_number": inh, "zero_offset": zo}
                except Exception as e:
                    row["recompute_error"] = "{}: {}".format(type(e).__name__, str(e)[:300])
        except Exception as e:
            row["error"] = "{}.{}: {}".format(type(e).__module__, type(e).__name__, str(e)[:400])
            row["seconds"] = round(time.time() - t0, 2)
        res["rows"].append(row)
        print(json.dumps({k: row.get(k) for k in ("shot", "pointname", "n", "sha_data_match", "sha_times_match",
                                                  "rel_diff", "data_is_float32_exact", "error")})[:600], flush=True)
    json.dump(res, open(out, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
