#!/usr/bin/env python3
"""Fetch a set of DIII-D signals for a list of shots through FDP, one HDF5 file and one status JSON per shot.

    fdp run --device d3d python fetch_signals.py --signals SPEC.json --shots shots.txt --out OUT [--lanes 16]
    (in PBS use toolkit/run_slice.pbs, which sets proxy, token check and environment)

Fetch only: full records exactly as returned (no trimming, filtering, resampling, alignment or filling).

SPEC.json (see toolkit/signals/):
  {"name": "core_basic",
   "signals": {
     "ip":    {"kind": "ptdata", "pointname": "ip"},
     "ipmhd": {"kind": "mds", "tree": "EFIT01", "node": "\\ipmhd", "dims": ["times"]},
     "mirnov": {"kind": "ptdata_regex", "pattern": "^MPI66M\\d{3}D$"}      # every index pointname that matches
   }}

Per signal the status is one of
  (PTDATA pointnames are case-insensitive; the index lists them upper-case, and ptdata_regex patterns match those.)
  ok      fetched and passed QA (PTDATA: times present, len(times) == len(data), times strictly increasing)
  absent  PTDATA: not listed in the pinned index for this shot. MDS: the error says the node or its data does not
          exist (absent_basis = "mds message", with the text kept), because MDS has no index to check against
  error   anything else, with the exact exception text (outages, bad workers, failed QA)
Shot state: fetched (no errors, >= 1 ok), no_data (nothing ok, nothing errored; an `ip` canary tells "no PTDATA for
the shot" from an outage), error (any error). Files are written only for `fetched` shots unless --keep-partial,
so OUT holds complete shots and every error shot is retried later (make_slices.py picks them up).

Data are stored in the dtype returned (float64 for calibrated PTDATA). --float32-checked stores a PTDATA channel as
float32 only when float32 keeps every distinct returned value distinct and ordered with rounding < 0.01 of the
smallest value step (the per-channel test the Mirnov stores used; they also re-fetched raw counts on a sample).
PTDATA time bases are stored once per distinct array under /timebases; MDS dims are stored with the signal.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
import re
import socket
import sys
import time
import warnings

import h5py
import numpy as np

warnings.simplefilter("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptdata_index  # noqa: E402

MDS_ABSENT = re.compile(r"TreeNNF|TreeNODATA|%TREE-[EW]-(NNF|NODATA)|node not found|no data available", re.I)


def code_sha():
    h = hashlib.sha256()
    for f in ("fetch_signals.py", "ptdata_index.py"):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def versions():
    try:
        from importlib.metadata import version
    except ImportError:
        return {}
    out = {}
    for p in ("fdp", "toksearch", "toksearch_d3d", "ptdata", "h5py", "numpy"):
        try:
            out[p] = version(p)
        except Exception as e:
            out[p] = "unknown ({})".format(type(e).__name__)
    return out


def exc_text(e):
    return "{}.{}: {}".format(type(e).__module__, type(e).__name__, e)


def err_text(err):
    """toksearch keeps per-signal errors in rec.errors[name]; reduce to the last traceback line."""
    if isinstance(err, dict):
        tb = err.get("traceback") or err.get("exception") or str(err)
        lines = [l for l in str(tb).strip().splitlines() if l.strip()]
        return lines[-1] if lines else str(err)
    if isinstance(err, BaseException):
        return exc_text(err)
    return str(err)


def make_signal(spec, name):
    if spec["kind"] in ("ptdata", "ptdata_regex"):
        from toksearch_d3d import PtDataSignal
        try:
            return PtDataSignal(name, keep_header=True)
        except TypeError:
            return PtDataSignal(name)
    if spec["kind"] == "mds":
        from toksearch import MdsSignal
        return MdsSignal(spec["node"], spec["tree"], dims=tuple(spec.get("dims", ("times",))))
    raise ValueError("unknown kind {}".format(spec["kind"]))


def fetch_one(sig, shot):
    from toksearch import Pipeline
    pipe = Pipeline([shot])
    pipe.fetch("x", sig)
    rec = pipe.compute_serial()[0]
    if "x" in rec.errors:
        return None, err_text(rec.errors["x"])
    return rec["x"], None


def header_attrs(h):
    out = {}
    if h is None:
        return out
    try:
        d = h.as_dict() if hasattr(h, "as_dict") else {}
    except Exception:
        d = {}
    for k, v in d.items():
        if isinstance(v, bytes):
            v = v.decode("ascii", "replace").strip()
        if isinstance(v, np.generic):
            v = v.item()
        if isinstance(v, (int, float, str, bool)):
            out["ptdata_" + k] = v
    return out


def float32_ok(d):
    d = np.asarray(d, dtype=np.float64)
    vals = np.unique(d[np.isfinite(d)])
    if vals.size < 2:
        return bool(np.array_equal(d.astype(np.float32).astype(np.float64), d, equal_nan=True)), None
    u32 = vals.astype(np.float32)
    distinct = np.unique(u32).size == vals.size and bool(np.all(np.diff(u32) > 0))
    step = float(np.min(np.diff(vals)))
    r = float(np.max(np.abs(u32.astype(np.float64) - vals))) / step
    return bool(distinct and r < 0.01), r


def expand(spec_signals, listed):
    """(output name, spec, pointname or None) for every signal; ptdata_regex expands against the index."""
    out = []
    for name, s in spec_signals.items():
        if s["kind"] == "ptdata_regex":
            if listed is None:
                out.append((name, dict(s, unresolved=True), None))
            else:
                pat = re.compile(s["pattern"])
                out.extend((p, s, p) for p in sorted(listed) if pat.search(p))
        elif s["kind"] == "ptdata":
            out.append((name, s, s.get("pointname", name)))
        else:
            out.append((name, s, None))
    return out


def process_shot(args):
    shot, spec, out, opts, deadline = args
    if deadline and time.time() > deadline:
        return {"shot": shot, "state": "not_attempted", "ok": 0, "absent": 0, "error": 0, "MB": 0.0, "s": 0.0}
    t0 = time.time()
    st = {"shot": shot, "spec": spec.get("name"), "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          "host": socket.gethostname(), "pid": os.getpid(), "index_snapshot": os.environ.get("FDP_INDEX_SNAPSHOT"),
          "code_sha256": opts["code_sha"], "versions": opts["versions"]}
    needs_index = any(s["kind"] in ("ptdata", "ptdata_regex") for s in spec["signals"].values())
    listed, st["index_error"] = None, None
    if needs_index:
        for i in range(3):
            try:
                listed = {k.upper(): v for k, v in ptdata_index.read_index(shot).get("pointname_ext", {}).items()}
                st["index_error"] = None
                break
            except Exception as e:
                st["index_error"] = exc_text(e)[:400]
                time.sleep(5 * (i + 1))
    chans, payload, timebases = {}, {}, {}
    for name, s, pointname in expand(spec["signals"], listed):
        c = {"kind": s["kind"]}
        c.update({k: s[k] for k in ("pointname", "pattern", "tree", "node") if k in s})
        if pointname:
            c["pointname"] = pointname
        if s.get("unresolved"):
            c.update(status="error", exc="pattern not expanded: index unreadable")
            chans[name] = c
            continue
        if pointname is not None and listed is not None and pointname.upper() not in listed:
            c.update(status="absent", absent_basis="not in pinned PTDATA index")
            chans[name] = c
            continue
        if pointname is not None:
            c["index_ext"] = (listed or {}).get(pointname.upper())
        tc = time.time()
        try:
            rec, err = fetch_one(make_signal(s, pointname or name), shot)
        except Exception as e:
            rec, err = None, exc_text(e)
        c["seconds"] = round(time.time() - tc, 2)
        if err is not None:
            if s["kind"] == "mds" and MDS_ABSENT.search(err):
                c.update(status="absent", absent_basis="mds message", exc=err[:500])
            else:
                c.update(status="error", exc=err[:500])
            chans[name] = c
            continue
        d = np.asarray(rec["data"])
        c.update(dtype_returned=str(d.dtype), shape=list(d.shape),
                 units=str((rec.get("units", {}) or {}).get("data", "")) if isinstance(rec.get("units"), dict) else "",
                 sha256_data=hashlib.sha256(np.ascontiguousarray(d).tobytes()).hexdigest())
        dims = {k: np.asarray(rec[k]) for k in (s.get("dims") or ("times",)) if k in rec}
        qa = []
        if d.size == 0:
            qa.append("empty data")
        if s["kind"] != "mds":
            t = dims.get("times")
            if t is None:
                qa.append("no times returned")
            else:
                tt = np.asarray(t, dtype=np.float64)
                dt = np.diff(tt)
                c.update(n=int(tt.size), t_first=float(tt[0]) if tt.size else None,
                         t_last=float(tt[-1]) if tt.size else None,
                         dt_min=float(dt.min()) if dt.size else None, dt_max=float(dt.max()) if dt.size else None,
                         monotonic=bool(dt.size == 0 or np.all(dt > 0)))
                if tt.size != d.shape[0]:
                    qa.append("len(times) {} != len(data) {}".format(tt.size, d.shape[0]))
                if not c["monotonic"]:
                    qa.append("times not strictly increasing")
        else:
            c["dims"] = {k: {"shape": list(v.shape), "dtype": str(v.dtype)} for k, v in dims.items()}
        if qa:
            c.update(status="error", exc="QA: " + "; ".join(qa))
            chans[name] = c
            continue
        store32 = False
        if opts["float32_checked"] and s["kind"] != "mds" and d.dtype == np.float64:
            store32, ratio = float32_ok(d)
            c["float32_rounding_over_step"] = ratio
        c["stored_dtype"] = "float32" if store32 else str(d.dtype)
        c["header"] = header_attrs(rec.get("header")) if hasattr(rec, "get") else {}
        if s["kind"] != "mds":
            t = np.asarray(dims["times"])
            key = hashlib.sha256(np.ascontiguousarray(t).tobytes()).hexdigest()
            timebases.setdefault(key, ("tb{}".format(len(timebases)), t))
            c["timebase"] = timebases[key][0]
            dims = {}
        c["status"] = "ok"
        chans[name] = c
        payload[name] = (d.astype(np.float32) if store32 else d, dims)
    st["signals"] = chans
    for k in ("ok", "absent", "error"):
        st["n_" + k] = sum(1 for v in chans.values() if v["status"] == k)
    if st["index_error"] and needs_index:
        st["n_error"] += 1
    if st["n_ok"] == 0:
        try:
            rec, err = fetch_one(make_signal({"kind": "ptdata"}, "ip"), shot)
            st["canary_ip"] = err or "ok: {} samples".format(np.asarray(rec["data"]).size)
        except Exception as e:
            st["canary_ip"] = exc_text(e)
    st["state"] = "error" if st["n_error"] else ("fetched" if st["n_ok"] else "no_data")
    write = payload and (st["state"] == "fetched" or opts["keep_partial"])
    st["file_written"], st["bytes"], st["file_relpath"], st["sha256"] = False, 0, None, None
    if write:
        rel = os.path.join("{}xxx".format(shot // 1000), "{}.h5".format(shot))
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with h5py.File(path + ".tmp", "w") as f:
            f.attrs.update({"shot": shot, "spec": spec.get("name", ""), "state": st["state"],
                            "partial": st["state"] != "fetched", "source": "DIII-D via FDP (Pelican/OSDF)",
                            "index_snapshot": st["index_snapshot"] or "", "created_utc": st["created_utc"],
                            "versions": json.dumps(st["versions"]), "code_sha256": st["code_sha256"],
                            "trimmed": False, "resampled": False})
            if timebases:
                g = f.create_group("timebases")
                for _, (tbn, t) in timebases.items():
                    g.create_dataset(tbn, data=t, compression="gzip", compression_opts=4)
            for name, (d, dims) in payload.items():
                c = chans[name]
                grp = f.create_group(name.replace("/", "_"))
                grp.create_dataset("data", data=d, compression="gzip", compression_opts=4)
                for k, v in dims.items():
                    grp.create_dataset("dim_" + k, data=v, compression="gzip", compression_opts=4)
                a = {k: c[k] for k in ("kind", "pointname", "tree", "node", "units", "dtype_returned", "stored_dtype",
                                       "index_ext") if c.get(k) is not None}
                if "timebase" in c:
                    a["timebase"] = "/timebases/" + c["timebase"]
                a.update(c.get("header", {}))
                for k, v in a.items():
                    grp.attrs[k] = v
        os.replace(path + ".tmp", path)
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 24), b""):
                h.update(b)
        st.update(file_written=True, bytes=os.path.getsize(path), file_relpath=rel, sha256=h.hexdigest())
    st["seconds"] = round(time.time() - t0, 2)
    sd = os.path.join(out, "_status")
    os.makedirs(sd, exist_ok=True)
    p = os.path.join(sd, "{}.json".format(shot))
    with open(p + ".tmp", "w") as f:
        json.dump(st, f, indent=1, default=str)
    os.replace(p + ".tmp", p)
    return {"shot": shot, "state": st["state"], "ok": st["n_ok"], "absent": st["n_absent"], "error": st["n_error"],
            "MB": round(st["bytes"] / 1e6, 1), "s": st["seconds"]}


def done_state(out, shot):
    p = os.path.join(out, "_status", "{}.json".format(shot))
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p)).get("state")
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--signals", required=True, help="spec JSON (toolkit/signals/*.json)")
    ap.add_argument("--shots", required=True, help="text file, one shot per line (first column)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--lanes", type=int, default=1, help="worker processes, one shot each")
    ap.add_argument("--deadline-s", type=float, default=0, help="start no new shot after this many seconds")
    ap.add_argument("--keep-partial", action="store_true", help="also write files for shots with errors")
    ap.add_argument("--float32-checked", action="store_true", help="float32 for PTDATA channels that pass the check")
    ap.add_argument("--redo", action="store_true", help="refetch shots already fetched/no_data in OUT")
    a = ap.parse_args()
    spec = json.load(open(a.signals))
    deadline = time.time() + a.deadline_s if a.deadline_s else 0
    if any(s["kind"] in ("ptdata", "ptdata_regex") for s in spec["signals"].values()):
        ptdata_index.pin_ptdata_env()
    shots = [int(l.split()[0]) for l in open(a.shots) if l.strip() and not l.startswith("#")]
    skipped = [] if a.redo else [s for s in shots if done_state(a.out, s) in ("fetched", "no_data")]
    todo = [s for s in shots if s not in set(skipped)]
    os.makedirs(a.out, exist_ok=True)
    opts = {"code_sha": code_sha(), "versions": versions(), "float32_checked": a.float32_checked,
            "keep_partial": a.keep_partial}
    print("START", json.dumps({"shots": len(shots), "skipped_done": len(skipped), "lanes": a.lanes,
                               "index_snapshot": os.environ.get("FDP_INDEX_SNAPSHOT"), "versions": opts["versions"]}),
          flush=True)
    jobs = [(s, spec, a.out, opts, deadline) for s in todo]
    t0 = time.time()
    results = []
    if a.lanes <= 1:
        for j in jobs:
            r = process_shot(j)
            print(json.dumps(r), flush=True)
            results.append(r)
    else:
        with mp.get_context("fork").Pool(a.lanes) as pool:
            for r in pool.imap_unordered(process_shot, jobs):
                print(json.dumps(r), flush=True)
                results.append(r)
    wall = time.time() - t0
    good = sorted(r["s"] for r in results if r["state"] == "fetched")
    summ = {"shots": len(shots), "skipped_done": len(skipped), "lanes": a.lanes, "wall_s": round(wall, 1),
            "median_good_shot_s": good[len(good) // 2] if good else None,
            "s_per_shot_node": round(good[len(good) // 2] / max(1, a.lanes), 2) if good else None,
            "MB_total": round(sum(r["MB"] for r in results), 1),
            "states": {k: sum(1 for r in results if r["state"] == k) for k in ("fetched", "no_data", "error", "not_attempted")}}
    print("SUMMARY", json.dumps(summ), flush=True)
    with open(os.path.join(a.out, "run_summary_{}_{}.json".format(int(time.time()), os.getpid())), "w") as f:
        json.dump(dict(summ, results=results), f, indent=1)


if __name__ == "__main__":
    main()
