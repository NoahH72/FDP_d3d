#!/usr/bin/env python3
"""Mirnov job 3 (B1-B8) smoke report from work/smoke/T3_* status files. Read-only, stdlib only (runs on a login node).

  python3 code/smoke_report_t3.py > work/SMOKE_REPORT_T3.md
"""
import csv
import glob
import json
import os
import statistics as stats

ROOT = "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10"
S = os.path.join(ROOT, "work", "smoke")
ERAS = [("E1", 0, 152128), ("E2", 152129, 198185), ("L", 198186, 10 ** 7)]  # b2mhz eras of the saga bundle


def era(s):
    return next(e for e, a, b in ERAS if a <= s <= b)


def statuses(d):
    return {int(os.path.basename(p)[:-5]): json.load(open(p)) for p in glob.glob(os.path.join(S, d, "_status", "*.json"))}


def summary(d):
    ps = sorted(glob.glob(os.path.join(S, d, "run_summary_*.json")))
    return json.load(open(ps[-1])) if ps else None


def med(v):
    return stats.median(v) if v else float("nan")


def main():
    ref = {(int(r["shot"]), r["pointname"]): r for r in csv.DictReader(open(os.path.join(ROOT, "inputs", "reference_values_smoke.csv")))}
    sm = statuses("T3_smoke")
    out = ["# Mirnov job 3 smoke test (B1-B8), old env ptdata 1.4.6 over FDP\n",
           "Fetcher code/mirnov_fetch_t3.py (copy of the job 2 fetcher; channel set B1-B8, family b2mhz, labels). "
           "Outputs work/smoke/T3_*. Smoke shots: raw counts re-fetched on every channel.\n",
           "| shot | era | ok / index / saga expected | absent | errors | n per channel | t range ms | rate kHz | float32 / float64 | time bases | MB | s |",
           "|---|---|---|---|---|---|---|---|---|---:|---:|---:|"]
    idrows = []
    for s in sorted(sm):
        st = sm[s]
        ch = {k: v for k, v in st["channels"].items() if v["status"] == "ok"}
        ns = sorted({v["n"] for v in ch.values()})
        nnote = ", ".join("{}x{}".format(sum(1 for v in ch.values() if v["n"] == n), n) for n in ns) or "-"
        tr = "{:.1f} to {:.1f}".format(min(v["t_first_ms"] for v in ch.values()), max(v["t_last_ms"] for v in ch.values())) if ch else "-"
        rates = sorted({round((v.get("sample_rate_hz_nominal") or 0) / 1e3) for v in ch.values()})
        f32 = sum(1 for v in ch.values() if v.get("stored_dtype") == "float32")
        exp = st.get("expected") or {}
        absent = [k for k, v in st["channels"].items() if v["status"] == "absent"]
        err = ["{} ({})".format(k, (v.get("exc") or "")[:60]) for k, v in st["channels"].items() if v["status"] == "error"]
        tbs = len({v.get("timebase") for v in ch.values()})
        out.append("| {} | {} | {} / {} / {} | {} | {} | {} | {} | {} | {} / {} | {} | {:.1f} | {:.0f} |".format(
            s, era(s), len(ch), st["n_listed"], exp.get("n"), ",".join(absent) or "-", "; ".join(err) or "-", nnote, tr,
            "/".join(str(r) for r in rates) or "-", f32, len(ch) - f32, tbs, st["bytes"] / 1e6, st["seconds"]))
        for k, v in ch.items():
            r = ref.get((s, k))
            if r:
                idrows.append((s, k, v["sha256_data_float32_le"] == r["sha256_data_float32_le"],
                               v["sha256_times_float64_le"] == r["sha256_times_float64_le"], int(r["n"]) == v["n"]))
    out.append("\n## Identity vs saga reference (B channels in reference_values_smoke.csv)\n")
    out.append("| shot | channel | data sha (float32 LE) | times sha (float64 LE) | n |\n|---|---|---|---|---|")
    for s, k, a, b, c in idrows:
        out.append("| {} | {} | {} | {} | {} |".format(s, k, "match" if a else "DIFF", "match" if b else "DIFF", "ok" if c else "DIFF"))
    out.append("\n{}/{} bit-identical in data and times.".format(sum(1 for r in idrows if r[2] and r[3] and r[4]), len(idrows)))
    allch = [v for st in sm.values() for v in st["channels"].values() if v["status"] == "ok"]
    fc = [v["float32_check"] for v in allch]
    if fc:
        out.append("\n## float32 check ({} channels on {} shots, raw counts on every channel)\n".format(len(fc), len(sm)))
        out.append("- counts to values one-to-one: {}/{}".format(sum(f.get("count_to_value_one_to_one") is True for f in fc), len(fc)))
        out.append("- distinct counts == distinct values: {}/{}".format(sum(f.get("counts_equal_distinct_values") is True for f in fc), len(fc)))
        out.append("- float32 keeps every distinct value distinct and ordered: {}/{}".format(sum(f["float32_keeps_distinct_values"] for f in fc), len(fc)))
        ro = [f["rounding_over_step"] for f in fc if f.get("rounding_over_step") is not None]
        out.append("- float32 rounding / smallest value step: max {:.2e}, median {:.2e} (threshold 0.01)".format(max(ro), med(ro)))
        out.append("- raw times equal data times: {}/{}".format(sum(v.get("raw_times_equal_data_times") is True for v in allch), len(allch)))
        out.append("- stored float32: {}/{}".format(sum(f["float32_lossless"] for f in fc), len(fc)))
        out.append("- count range seen: {} to {}".format(min(f.get("count_min", 0) for f in fc), max(f.get("count_max", 0) for f in fc)))
        out.append("- t0 + i*dt rebuilds the times exactly: {}/{}; uniform within float noise: {}/{}".format(
            sum(v.get("t0_plus_i_dt_exact") is True for v in allch), len(allch), sum(v.get("uniform") is True for v in allch), len(allch)))
    out.append("\n## Negative controls\n")
    for s, st in sorted(statuses("T3_neg").items()):
        exp = st.get("expected") or {}
        out.append("- {}: state {}, listed {}, ok {}, absent {}, error {}; saga expected {} ({}); index error: {}; ip canary: {}".format(
            s, st["state"], st["n_listed"], st["n_ok"], st["n_absent"], st["n_error"], exp.get("n"), exp.get("source"),
            (st.get("index_error") or "none")[:160], st.get("canary_ip", "not run (channels fetched)")))
    out.append("\n## Throughput (one node)\n")
    out.append("| run | lanes | shots done | wall s | errors | median good-shot s | s/shot (median / lanes) | median channel read s (no raw re-fetch) | MB |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    per_era, sec_era = {}, {}
    for d in ("T3_smoke", "T3_l16", "T3_l48"):
        smy = summary(d)
        sts = statuses(d)
        good = [st for st in sts.values() if st["state"] == "fetched"]
        for st in good:
            per_era.setdefault(era(st["shot"]), []).append(st["bytes"] / 1e6)
        if not smy:
            continue
        gs = med([st["seconds"] for st in good if era(st["shot"]) != "E1"])
        rd = med([v["seconds"] for st in good if not st["raw_count_check"] and era(st["shot"]) != "E1"
                  for v in st["channels"].values() if v["status"] == "ok" and v.get("seconds")])
        sec_era.setdefault(smy["lanes"], gs / smy["lanes"])
        out.append("| {} | {} | {} | {} | {} | {:.0f} | {:.2f} | {:.2f} | {:.0f} |".format(
            d, smy["lanes"], smy["attempted"], smy["wall_s"], smy["states"]["error"], gs, gs / smy["lanes"], rd, smy["MB_total"]))
    out.append("\nTimes exclude E1 shots (B1 and B5 only, 1 MHz), which are small.")
    sizes = {r["era"]: int(r["n_shots"]) for r in csv.DictReader(open(os.path.join(ROOT, "inputs", "sizes_by_tier.csv")))
             if r["tier"] == "tier3" and r["family"] == "b2mhz"}
    out.append("\n## Projection (tier 3 list, 51,522 shots)\n\n| era | shots | measured MB/shot (n) | projected TB |\n|---|---:|---|---:|")
    tot = tot_post = 0.0
    for e, _, _ in ERAS:
        v = per_era.get(e)
        tb = sizes.get(e, 0) * (stats.mean(v) if v else 0) / 1e6
        tot += tb
        tot_post += tb if e != "E1" else 0
        out.append("| {} | {} | {} | {:.3f} |".format(e, sizes.get(e), "{:.1f} ({})".format(stats.mean(v), len(v)) if v else "not measured", tb))
    out.append("| **total** | {} | | **{:.2f}** (from 152129 only: {:.2f}) |".format(sum(sizes.values()), tot, tot_post))
    n_post = sizes.get("E2", 0) + sizes.get("L", 0)
    for lanes, sps in sorted(sec_era.items()):
        out.append("\nAt {} lanes: {:.2f} s/shot per node, so {:,} shots from 152129 take about {:.0f} node-hours.".format(
            lanes, sps, n_post, n_post * sps / 3600))
    print("\n".join(out))


if __name__ == "__main__":
    main()
