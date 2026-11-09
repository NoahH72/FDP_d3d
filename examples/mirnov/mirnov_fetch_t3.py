#!/usr/bin/env python3
"""Mirnov job 3 fetcher: B1-B8 (saga tier 3; 2 MHz, 8,388,608 samples from 152129; only B1 and B5, 1 MHz, before),
old FDP env (ptdata 1.4.6). Copy of mirnov_fetch_t2.py (kept unchanged as the job 2 provenance); only the channel set,
the expected-family name and labels differ. No burst flag (that was a dB/dt property); no toroidal angle from the name.

Run under the old env:  $FDP_CLI run $FDP_PY mirnov_fetch_t3.py --shots LIST --out DIR [--lanes N] [--raw-check 1]

Fetch only: full records as returned by PTDATA (toksearch PtDataSignal, ical=1), no trimming, filtering, resampling
or filling. Per shot it writes OUT/<shot//1000>xxx/<shot>.h5 (atomic .tmp + rename) and OUT/_status/<shot>.json.

Channel classification uses the pinned PTDATA json index (the same index reader the BES/ECEI writers use), because
FDP reports an absent pointname and a missing shot with the same exception:
  ok      listed in the index and fetched (>= 10 samples, times monotone, len(times) == len(data))
  absent  not listed in the index for this shot
  error   listed but the fetch failed, or failed QA; exact exception text recorded
Data are stored as float32 only when the per-channel check passes: with the raw counts (ical=0) the count -> value
map is one-to-one and float32 keeps every distinct value distinct, in order, with rounding < 1e-3 of the smallest
value step. Otherwise that channel is stored as float64 and flagged. Each distinct time base is stored once as
float64 exactly as returned; channels reference it by name.
"""
import argparse
import csv
import hashlib
import json
import multiprocessing as mp
import os
import re
import socket
import sys
import tempfile
import time
import traceback
import warnings

import h5py
import numpy as np

warnings.simplefilter("ignore")
ROOT = "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10"
INPUTS = os.path.join(ROOT, "inputs")
INDEX_BASE = "pelican://osg-htc.org:443/fdp-d3d/archives/index/json"
STALE = "json_indexes_2026-01-13_12:22:11"
PATTERN = re.compile(r"^B([1-8])$")  # group 1 channel number
MIN_SAMPLES = 10
NONSENSE_T0_SHOTS = set()  # the handoff's three nonsense-t0 shots were dB/dt headers; none known for B
KIND = "B1-B8 (saga tier 3 family b2mhz; physical identity not given by PTDATA or the handoff, see OPEN_ITEMS G1)"
FAMILY = "B1-B8 (job 3: saga tier 3)"


def _code_sha():
    h = hashlib.sha256()
    with open(os.path.abspath(__file__), "rb") as f:
        h.update(f.read())
    return h.hexdigest()


CODE_SHA = _code_sha()
try:
    from importlib.metadata import version as _v
    VERSIONS = {p: _v(p) for p in ("toksearch", "toksearch_d3d", "ptdata", "h5py", "numpy")}
except Exception as _e:
    VERSIONS = {"error": str(_e)}


def setup_index():
    snap = os.environ.get("FDP_INDEX_SNAPSHOT") or open(os.path.expanduser("~/.fdp/latest_index_snapshot")).read().strip()
    idx = os.environ.get("PTDATA_JSON_INDEX_DIR", "")
    os.environ["PTDATA_JSON_INDEX_DIR"] = "{}/{}".format(INDEX_BASE, snap)
    sys.path.insert(0, "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/ECEI-Data/bes_polaris")
    import bes_prestage  # index reader only (read-only use of the production module)
    bes_prestage._INDEX_BASE = os.environ["PTDATA_JSON_INDEX_DIR"]
    return snap, bes_prestage


def load_expected():
    exp, files = {}, {}
    with open(os.path.join(INPUTS, "expected_channels_mirnov.csv")) as f:
        for r in csv.DictReader(f):
            if r["family"] != "b2mhz":
                continue
            names = r["names"]
            if names.startswith("@"):
                if names not in files:
                    files[names] = [l.strip() for l in open(os.path.join(INPUTS, names[1:])) if l.strip()]
                names = files[names]
            else:
                names = [x for x in names.split(";") if x]
            names = [x for x in names if PATTERN.match(x)]
            exp[int(r["shot"])] = {"era": r["era"], "n": len(names), "names": names, "source": r["source"]}
    return exp


def exc_text(e):
    return "{}.{}: {}".format(type(e).__module__, type(e).__name__, e)


def scalarize(v):
    if isinstance(v, bytes):
        return v.decode("ascii", "replace").strip()
    if isinstance(v, np.generic):
        return v.item()
    return v


def header_attrs(h):
    out = {}
    try:
        for k, v in h.as_dict().items():
            v = scalarize(v)
            if isinstance(v, (int, float, str, bool)):
                out["ptdata_" + k] = v
    except Exception as e:
        out["ptdata_as_dict_error"] = exc_text(e)
    for k in ("rc_over_g", "inherent_number", "zoff", "nbits", "dfi", "numpoints", "pzero"):
        try:
            out["ptdata_" + k] = scalarize(getattr(h, k)())
        except Exception as e:
            out["ptdata_" + k + "_error"] = exc_text(e)
    for k in ("units", "clock", "dtype"):
        try:
            out["ptdata_" + k] = scalarize(getattr(h, k)())
        except Exception as e:
            out["ptdata_" + k + "_error"] = exc_text(e)
    arrays = {}
    try:
        ia, ra = h.fixed_headers()
        arrays["ptdata_fixed_iarray"] = np.asarray(ia)
        arrays["ptdata_fixed_rarray"] = np.asarray(ra)
    except Exception as e:
        out["ptdata_fixed_headers_error"] = exc_text(e)
    return out, arrays


def float32_check(d, raw):
    """Is float32 storage lossless for this channel? Returns (ok, details)."""
    d = np.asarray(d, dtype=np.float64)
    v32 = d.astype(np.float32)
    det = {"returned_is_float32_exact": bool(np.array_equal(v32.astype(np.float64), d))}
    vals = np.unique(d)
    u32 = vals.astype(np.float32)
    det["n_distinct_values"] = int(vals.size)
    det["float32_keeps_distinct_values"] = bool(np.unique(u32).size == vals.size and np.all(np.diff(u32) > 0))
    step = float(np.min(np.diff(vals))) if vals.size > 1 else None
    maxerr = float(np.max(np.abs(u32.astype(np.float64) - vals))) if vals.size else 0.0
    det.update(min_value_step=step, max_float32_rounding=maxerr,
               rounding_over_step=(maxerr / step) if step else None)
    # A count stays exactly recoverable while the rounding is < 0.5 of the smallest value step; require a 50x
    # margin (< 0.01 step). (1e-3 was used for the first smoke pass on 2026-10-27; full-range 16-bit channels
    # such as 185000 MPI66M020D reach 0.0015.)
    det["threshold_rounding_over_step"] = 0.01
    ok = det["float32_keeps_distinct_values"] and (step is None or maxerr < 0.01 * step)
    if raw is not None:
        raw = np.asarray(raw).astype(np.int64)
        det["raw_dtype"] = str(np.asarray(raw).dtype)
        if raw.size != d.size:
            det["raw_len_mismatch"] = [int(raw.size), int(d.size)]
            ok = False
        else:
            order = np.argsort(raw, kind="stable")
            rs, ds = raw[order], d[order]
            brk = np.flatnonzero(np.diff(rs)) + 1
            starts = np.r_[0, brk]
            ends = np.r_[brk, rs.size]
            one_to_one = bool(np.all([np.all(ds[a:b] == ds[a]) for a, b in zip(starts, ends)]))
            det.update(n_distinct_counts=int(starts.size), count_min=int(rs[0]), count_max=int(rs[-1]),
                       count_to_value_one_to_one=one_to_one,
                       counts_equal_distinct_values=bool(starts.size == vals.size))
            if not one_to_one:  # diagnostic: is the raw array merely shifted?
                for sh in (-4, -3, -2, -1, 1, 2, 3, 4):
                    a_, b_ = (raw[sh:], d[:-sh]) if sh > 0 else (raw[:sh], d[-sh:])
                    o = np.argsort(a_, kind="stable"); ra, da = a_[o], b_[o]
                    br = np.r_[0, np.flatnonzero(np.diff(ra)) + 1, ra.size]
                    if all(np.all(da[x:y] == da[x]) for x, y in zip(br[:-1], br[1:])):
                        det["raw_aligned_with_shift"] = sh
                        break
            ok = ok and one_to_one and starts.size == vals.size
    det["float32_lossless"] = bool(ok)
    return bool(ok), det


def time_info(t):
    t = np.asarray(t, dtype=np.float64)
    d = np.diff(t)
    n = t.size
    info = {"n": int(n), "t_first_ms": float(t[0]), "t_last_ms": float(t[-1]),
            "dt_min_ms": float(d.min()) if n > 1 else None, "dt_max_ms": float(d.max()) if n > 1 else None,
            "monotonic": bool(n < 2 or np.all(d > 0))}
    if n > 1:
        dt_mean = (t[-1] - t[0]) / (n - 1)
        info["dt_nominal_ms"] = float(dt_mean)
        info["sample_rate_hz_nominal"] = float(1e3 / dt_mean) if dt_mean > 0 else None
        rec = t[0] + np.arange(n, dtype=np.float64) * dt_mean
        info["t0_plus_i_dt_exact"] = bool(np.array_equal(rec, t))
        info["t0_plus_i_dt_max_err_ms"] = float(np.max(np.abs(rec - t)))
        # uniform within float noise? (multi-clock records are not)
        info["uniform"] = bool(d.max() - d.min() < 1e-6 * abs(dt_mean))
    return info


def process_shot(args):
    shot, out, raw_every, expected, snap, deadline = args
    if deadline and time.time() > deadline:
        return {"shot": shot, "state": "not_attempted", "ok": 0, "absent": 0, "error": 0, "listed": None, "MB": 0.0, "s": 0.0}
    raw_check = bool(raw_every) and shot % raw_every == 0
    t0 = time.time()
    from toksearch_d3d import PtDataSignal  # old env: toksearch_d3d 0.4.0
    import bes_prestage
    st = {"shot": shot, "family": FAMILY, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          "host": socket.gethostname(), "pid": os.getpid(), "index_snapshot": snap}
    exp = expected.get(shot)
    st["expected"] = {"n": exp["n"], "era": exp["era"], "source": exp["source"]} if exp else None
    st["expected_n_channels"] = exp["n"] if exp else None
    st["list"] = "shots_mirnov_tier3.txt"
    st["raw_count_check"] = raw_check
    st["raw_count_check_rule"] = "raw counts re-fetched (ical=0) when shot % {} == 0; distinctness check on every channel".format(raw_every)
    exp_names = set(exp["names"]) if exp else set()
    # index
    listed, idx_err = None, None
    stager = bes_prestage.ShotPreStager(channels=[], cache_dir=tempfile.mkdtemp(prefix="mir_idx_"))
    for i in range(3):
        try:
            pe = stager._read_index(shot).get("pointname_ext", {})
            listed = {k: v for k, v in pe.items() if PATTERN.match(k)}
            idx_err = None
            break
        except Exception as e:
            idx_err = exc_text(e)
            time.sleep(10 * (i + 1))
    st["index_error"] = idx_err
    st["n_listed"] = len(listed) if listed is not None else None
    names = sorted(set(listed or {}) | exp_names)
    chans, payload, timebases = {}, {}, {}
    for ch in names:
        c = {"channel_number_from_name": int(PATTERN.match(ch).group(1)), "kind": KIND,
             "in_index": bool(listed is not None and ch in listed), "in_saga_expected": ch in exp_names}
        if listed is not None and ch not in listed:
            c["status"] = "absent"
            chans[ch] = c
            continue
        c["index_ext"] = (listed or {}).get(ch)
        tc = time.time()
        try:
            g = PtDataSignal(ch, keep_header=True).gather(shot)
            d, t = np.asarray(g["data"]), np.asarray(g["times"])
            raw = None
            if raw_check:
                # fetch_times=True: on ptdata 1.4.6 the fetch_times=False path returned counts not aligned
                # sample-for-sample with the ical=1 data (smoke test 2026-10-27, shot 185000)
                rg = PtDataSignal(ch, ical=0, fetch_units=False).gather(shot)
                raw = np.asarray(rg["data"])
                c["raw_times_equal_data_times"] = bool(np.array_equal(np.asarray(rg["times"]), t))
            c["seconds"] = round(time.time() - tc, 2)
            c["units_returned"] = str(g.get("units", {}).get("data"))
            c["dtype_returned"] = str(d.dtype)
            c.update(time_info(t))
            c["sha256_data_float32_le"] = hashlib.sha256(d.astype("<f4").tobytes()).hexdigest()
            c["sha256_times_float64_le"] = hashlib.sha256(t.astype("<f8").tobytes()).hexdigest()
            c["sha256_data_float64_le"] = hashlib.sha256(d.astype("<f8").tobytes()).hexdigest()
            hattrs, harrays = header_attrs(g["header"])
            c["header"] = hattrs
            ok32, det = float32_check(d, raw)
            c["float32_check"] = det
            c["stored_dtype"] = "float32" if ok32 else "float64"
            qa = []
            if d.size < MIN_SAMPLES:
                qa.append("short record (< {} samples)".format(MIN_SAMPLES))
            if t.size != d.size:
                qa.append("len(times) {} != len(data) {}".format(t.size, d.size))
            if not c["monotonic"]:
                qa.append("times not monotonic")
            if qa:
                c["status"] = "error"
                c["exc"] = "; ".join(qa)
            else:
                c["status"] = "ok"
                key = c["sha256_times_float64_le"]
                if key not in timebases:
                    timebases[key] = ("tb{}".format(len(timebases)), t)
                c["timebase"] = timebases[key][0]
                payload[ch] = (d, harrays, ok32)
        except Exception as e:
            c["status"] = "error"
            c["exc"] = exc_text(e)
            c["seconds"] = round(time.time() - tc, 2)
        chans[ch] = c
    st["channels"] = chans
    for k in ("ok", "absent", "error"):
        st["n_" + k] = sum(1 for v in chans.values() if v["status"] == k)
    if shot in NONSENSE_T0_SHOTS:
        st["flag_nonsense_header_t0"] = True
    # canary when nothing could be fetched
    if st["n_ok"] == 0:
        try:
            g = PtDataSignal("ip").gather(shot)
            st["canary_ip"] = "ok: {} samples".format(len(g["data"]))
        except Exception as e:
            st["canary_ip"] = exc_text(e)
    # write file
    path = os.path.join(out, "{}xxx".format(shot // 1000), "{}.h5".format(shot))
    st["file_written"] = False
    if payload:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with h5py.File(tmp, "w") as f:
            rates = sorted({round(chans[ch].get("sample_rate_hz_nominal") or 0) for ch in payload})
            f.attrs.update({"shot": shot, "family": "B1-B8", "tier": "3",
                            "description": "DIII-D B1-B8 (saga tier 3: 2 MHz from 152129, B1 and B5 at 1 MHz before), raw PTDATA as returned",
                            "n_channels": len(payload), "channels": ",".join(payload),
                            "data_dtype_note": "float32 where the per-channel lossless check passed (see attrs float32_lossless); float64 otherwise",
                            "source": "PTDATA via FDP (Pelican/OSDF), toksearch PtDataSignal ical=1, old env ptdata 1.4.6",
                            "index_snapshot": snap, "sample_rate_hz": rates[0] if len(rates) == 1 else -1,
                            "sample_rates_hz": rates, "time_units": "ms", "trimmed": False, "resampled": False})
            if shot in NONSENSE_T0_SHOTS:
                f.attrs["flag_nonsense_header_t0"] = True
            gtb = f.create_group("timebases")
            for key, (name, t) in timebases.items():
                ds = gtb.create_dataset(name, data=np.asarray(t, dtype=np.float64), compression="gzip", compression_opts=4)
                ds.attrs["units"] = "ms"
            for ch, (d, harrays, ok32) in payload.items():
                c = chans[ch]
                grp = f.create_group(ch)
                ds = grp.create_dataset("data", data=d.astype(np.float32 if ok32 else np.float64),
                                        compression="gzip", compression_opts=4)
                a = {"pointname": ch, "timebase": "/timebases/" + c["timebase"], "n_samples": c["n"],
                     "t_first_ms": c["t_first_ms"], "t_last_ms": c["t_last_ms"], "dt_min_ms": c["dt_min_ms"],
                     "dt_max_ms": c["dt_max_ms"], "dt_nominal_ms": c.get("dt_nominal_ms"),
                     "sample_rate_hz_nominal": c.get("sample_rate_hz_nominal"), "units_returned": c["units_returned"],
                     "dtype_returned": c["dtype_returned"], "stored_dtype": c["stored_dtype"],
                     "float32_lossless": c["float32_check"]["float32_lossless"],
                     "channel_number_from_name": c["channel_number_from_name"], "kind": c["kind"],
                     "index_ext": c.get("index_ext") or ""}
                a.update(c["header"])
                for k, v in a.items():
                    if v is None:
                        v = np.nan if k not in ("index_ext",) else ""
                    grp.attrs[k] = v
                for k, v in harrays.items():
                    grp.attrs[k] = v
        os.replace(tmp, path)
        st["file_written"] = True
        st["bytes"] = os.path.getsize(path)
        st["file_relpath"] = os.path.relpath(path, out)
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 24), b""):
                h.update(b)
        st["sha256"] = h.hexdigest()
    else:
        st["bytes"] = 0
    if st["index_error"]:
        st["state"] = "error"
    elif st["n_error"]:
        st["state"] = "error"
    elif st["n_ok"]:
        st["state"] = "fetched"
    else:
        st["state"] = "no_data"
    st["qa_pass"] = st["state"] == "fetched"
    st.setdefault("sha256", None)
    st.setdefault("file_relpath", None)
    st["seconds"] = round(time.time() - t0, 2)
    st["seconds_amortized"] = st["seconds"]
    st["code_sha256"] = CODE_SHA
    st["versions"] = VERSIONS
    sd = os.path.join(out, "_status")
    os.makedirs(sd, exist_ok=True)
    p = os.path.join(sd, "{}.json".format(shot))
    with open(p + ".tmp", "w") as f:
        json.dump(st, f, indent=1, default=str)
    os.replace(p + ".tmp", p)
    return {"shot": shot, "state": st["state"], "ok": st["n_ok"], "absent": st["n_absent"], "error": st["n_error"],
            "listed": st["n_listed"], "MB": round(st["bytes"] / 1e6, 1), "s": st["seconds"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lanes", type=int, default=1)
    ap.add_argument("--raw-check", type=int, default=1, help="re-fetch raw counts for every Nth shot (1 = all, 0 = none)")
    ap.add_argument("--deadline-s", type=float, default=0, help="do not start shots after this many seconds")
    a = ap.parse_args()
    deadline = time.time() + a.deadline_s if a.deadline_s else 0
    snap, _ = setup_index()
    expected = load_expected()
    shots = [int(l.split()[0]) for l in open(a.shots) if l.strip()]
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    jobs = [(s, a.out, a.raw_check, expected, snap, deadline) for s in shots]
    if a.lanes == 1:
        results = [process_shot(j) for j in jobs]
        for r in results:
            print(json.dumps(r), flush=True)
    else:
        with mp.get_context("fork").Pool(a.lanes) as pool:
            results = []
            for r in pool.imap_unordered(process_shot, jobs):
                print(json.dumps(r), flush=True)
                results.append(r)
    wall = time.time() - t0
    done = [r for r in results if r["state"] != "not_attempted"]
    summ = {"shots": len(shots), "attempted": len(done), "lanes": a.lanes, "raw_check_every": a.raw_check,
            "wall_s": round(wall, 1), "s_per_shot": round(wall / max(1, len(done)), 1),
            "MB_total": round(sum(r["MB"] for r in done), 1),
            "states": {s: sum(1 for r in results if r["state"] == s) for s in ("fetched", "no_data", "error", "not_attempted")}}
    print("SUMMARY", json.dumps(summ), flush=True)
    with open(os.path.join(a.out, "run_summary_{}.json".format(int(time.time()))), "w") as f:
        json.dump(dict(summ, results=results), f, indent=1)


if __name__ == "__main__":
    main()
