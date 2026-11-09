#!/usr/bin/env python3
"""Tier-1 final report from transfer/Mirnov_T1_MPI66M/_status/*.json (+ staged error statuses). Read-only.

  python3 final_report.py > work/FINAL_REPORT_T1.md
"""
import collections
import csv
import glob
import json
import os

ROOT = "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10"
STORE = os.path.join(ROOT, "transfer", "Mirnov_T1_MPI66M")
ERAS = [("E1", 125000, 131672), ("E2", 131673, 149580), ("E3", 149581, 152128), ("E4", 152129, 162690),
        ("E5", 162691, 174408), ("E6", 174409, 177975), ("E7", 177976, 198185), ("L1", 198186, 205533),
        ("L2", 205534, 207046)]
# handoff §4.1 expectations for the tier-1 set
EXP_CH = {"E1": 11, "E2": 11, "E3": 11}
EXP_N = {"E1": {2097152, 131072}, "E2": {2097152, 131072}, "E3": {2031616},
         "E4": set(range(2035936, 2097153)), "E5": {2031616, 2039808}, "E6": {2031616}, "E7": {2031616},
         "L1": {2031616, 4000000}, "L2": {5000000}}
EXP_RATES = {50000, 100000, 200000, 500000}


def era(s):
    return next(e for e, a, b in ERAS if a <= s <= b)


def main():
    ledger = {int(r["shot"]): r["state"] for r in csv.DictReader(open(os.path.join(ROOT, "work", "ledger.csv")))}
    E = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    odd_n, odd_rate, odd_ch, multi_tb, raw_fail, not_f32 = [], [], [], [], [], []
    raw_n = raw_ok = 0
    bytes_era = collections.Counter()
    for p in glob.glob(os.path.join(STORE, "_status", "*.json")):
        st = json.load(open(p))
        s, e = st["shot"], era(st["shot"])
        E[e]["state"][st["state"]] += 1
        if st["state"] != "fetched":
            continue
        bytes_era[e] += st["bytes"]
        ok = {k: v for k, v in st["channels"].items() if v["status"] == "ok"}
        E[e]["n_ch"][len(ok)] += 1
        exp = EXP_CH.get(e, 14)
        if len(ok) != exp:
            odd_ch.append((s, len(ok), st["n_listed"], st.get("expected_n_channels")))
        rates = {round(v["sample_rate_hz_nominal"] or 0, -3) for v in ok.values()}
        for r in rates:
            E[e]["rate"][int(r)] += 1
            if int(r) not in EXP_RATES:
                odd_rate.append((s, int(r)))
        if len({v.get("timebase") for v in ok.values()}) > 2:
            multi_tb.append((s, len({v.get("timebase") for v in ok.values()})))
        for k, v in ok.items():
            E[e]["n"][v["n"]] += 1
            E[e]["units"][v.get("units_returned")] += 1
            E[e]["burst"][bool(v.get("burst"))] += 1
            if v["n"] not in EXP_N[e]:
                odd_n.append((s, k, v["n"]))
            if v.get("stored_dtype") != "float32":
                not_f32.append((s, k))
        rc = st.get("raw_count_check")
        if rc:
            raw_n += 1
            good = all(c.get("count_to_value_one_to_one") is not False for c in
                       (v.get("float32_check", {}) for v in ok.values()))
            raw_ok += good
            if not good:
                raw_fail.append(s)
    out = ["# Mirnov tier 1 (MPI66M###D): final fetch report\n"]
    tot = collections.Counter(ledger.values())
    out.append("Ledger: " + ", ".join("{} {}".format(k, v) for k, v in sorted(tot.items())) +
               " (target 52,143).\n")
    out.append("| era | fetched | no_data | channels/shot | rates kHz (shots) | samples/channel | units | burst ch | GB |")
    out.append("|---|---:|---:|---|---|---|---|---:|---:|")
    for e, _, _ in ERAS:
        d = E[e]
        out.append("| {} | {} | {} | {} | {} | {} | {} | {} | {:.0f} |".format(
            e, d["state"]["fetched"], d["state"]["no_data"],
            ", ".join("{}×{}".format(n, c) for n, c in sorted(d["n_ch"].items())),
            ", ".join("{:g}:{}".format(r / 1e3, c) for r, c in sorted(d["rate"].items())),
            ", ".join("{}:{}".format(n, c) for n, c in d["n"].most_common(4)) + (" …" if len(d["n"]) > 4 else ""),
            ", ".join("'{}'".format(u) for u in d["units"]), d["burst"][True], bytes_era[e] / 1e9))
    out.append("\n## Checks\n")
    out.append("- stored float32 (lossless check passed): all channels except {} ({})".format(len(not_f32), not_f32[:10]))
    out.append("- raw-count re-check: {} shots, one-to-one on every channel: {}; failures: {}".format(raw_n, raw_ok, raw_fail[:20]))
    out.append("- shots with channel count != era norm (11 before 152129, 14 after): {}".format(len(odd_ch)))
    for x in sorted(odd_ch)[:40]:
        out.append("  - {} ok {} / listed in index {} / saga expected {}".format(*x))
    out.append("- channel lengths outside handoff §4.1: {} channels on {} shots".format(len(odd_n), len({x[0] for x in odd_n})))
    c = collections.Counter((era(s), n) for s, _, n in odd_n)
    for (e, n), k in c.most_common(15):
        out.append("  - {} n={}: {} channels".format(e, n, k))
    out.append("- rates outside 50/100/200/500 kHz: {} ({})".format(len(odd_rate), sorted(set(odd_rate))[:20]))
    out.append("- shots with > 2 distinct time bases: {} ({})".format(len(multi_tb), multi_tb[:10]))
    print("\n".join(out))


if __name__ == "__main__":
    main()
