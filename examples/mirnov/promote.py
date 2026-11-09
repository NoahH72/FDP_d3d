#!/usr/bin/env python3
"""Promote QA-passed staged shots into transfer/<store>/, then rebuild MANIFEST.sha256 and FETCH_SUMMARY.json.

  promote.py DIAG CHUNK [--dry-run]

Moves (os.rename, same filesystem, atomic) for every ledger row of CHUNK in state 'fetched' whose staged
status JSON says qa_pass and whose file size and sha256-at-QA still match; and moves the status JSON of
'no_data' shots (final state, no file). 'error' shots stay in staging until the retry pass.
Never overwrites an existing file in transfer/. Run on a login node (metadata + small files only).
"""
import collections
import json
import os
import sys

from common import STAGING, STORE, WORK, h5_path, ledger_locked, sha256_file, utcnow


def ingest(diag):
    """Copy each staged status's state into the ledger (the multi-process fetcher does not touch the ledger)."""
    st_dir = STAGING[diag]
    sd = os.path.join(st_dir, "_status")
    if not os.path.isdir(sd):
        return 0
    n = 0
    with ledger_locked() as (rows, save):
        for fn in os.listdir(sd):
            if not fn.endswith(".json"):
                continue
            st = json.loads(open(os.path.join(sd, fn), "rb").read().rstrip(b"\x00"))
            r = rows.get((diag, int(st["shot"])))
            if r is None or r["state"] in ("promoted", "on_aurora", "local_deleted"):
                continue
            if r["state"] != st["state"] or r["n_channels"] != str(st.get("n_ok")):
                r["state"] = st["state"]
                r["n_channels"] = str(st.get("n_ok"))
                r["n_listed"] = "" if st.get("n_listed") is None else str(st.get("n_listed"))
                r["bytes"] = str(st.get("bytes", 0))
                exp = st.get("expected_n_channels")
                r["note"] = "fewer than expected ({}<{})".format(st.get("n_ok"), exp) if exp and st.get("n_ok", 0) < exp and st["state"] == "fetched" else ""
                r["updated_utc"] = utcnow()
                n += 1
        save()
    return n


def promote(diag, chunk, dry=False):
    print("ingested", ingest(diag), "status changes")
    st_dir, store = STAGING[diag], STORE[diag]
    os.makedirs(os.path.join(store, "_status"), exist_ok=True)
    moved, skipped = [], []
    with ledger_locked() as (rows, save):
        for (d, shot), r in sorted(rows.items()):
            if d != diag or (chunk != "ALL" and r["chunk"] != chunk) or r["state"] not in ("fetched", "no_data"):
                continue
            sj = os.path.join(st_dir, "_status", "{}.json".format(shot))
            if not os.path.exists(sj):
                skipped.append((shot, "no status json"))
                continue
            st = json.loads(open(sj, "rb").read().rstrip(b"\x00"))
            dst_status = os.path.join(store, "_status", "{}.json".format(shot))
            if os.path.exists(dst_status):
                skipped.append((shot, "status already in transfer"))
                continue
            if r["state"] == "fetched":
                src = h5_path(diag, st_dir, shot)
                dst = h5_path(diag, store, shot)
                if not st.get("qa_pass") or not os.path.exists(src):
                    skipped.append((shot, "not qa_pass or file missing"))
                    continue
                if os.path.getsize(src) != st["bytes"]:
                    skipped.append((shot, "size changed since QA"))
                    continue
                if os.path.exists(dst):
                    skipped.append((shot, "destination exists"))
                    continue
                if not dry:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    os.rename(src, dst)
            st["promoted_utc"] = utcnow()
            st["file_relpath"] = os.path.relpath(h5_path(diag, store, shot), store) if r["state"] == "fetched" else None
            if not dry:
                with open(dst_status, "x") as f:
                    json.dump(st, f, indent=1, default=str)
                os.remove(sj)
                r["state"] = "promoted" if r["state"] == "fetched" else "no_data"
                r["note"] = (r["note"] + "; " if r["note"] else "") + "status in transfer"
                r["updated_utc"] = utcnow()
            moved.append(shot)
        if not dry:
            save()
    print("{} {}: promoted {} (incl. no_data status), skipped {}".format(diag, chunk, len(moved), len(skipped)))
    for s in skipped[:30]:
        print("  skip", s)
    if not dry:
        rebuild(diag)


def rebuild(diag):
    """MANIFEST.sha256 (relative paths): h5 hashes come from the QA-time sha in each status file
    (re-verified by size); status files, README and FETCH_SUMMARY are hashed directly."""
    store = STORE[diag]
    statuses = {}
    for fn in os.listdir(os.path.join(store, "_status")):
        if fn.endswith(".json"):
            statuses[int(fn[:-5])] = json.load(open(os.path.join(store, "_status", fn)))
    summary = summarize(diag, statuses)
    with open(os.path.join(store, "FETCH_SUMMARY.json.tmp"), "w") as f:
        json.dump(summary, f, indent=1)
    os.replace(os.path.join(store, "FETCH_SUMMARY.json.tmp"), os.path.join(store, "FETCH_SUMMARY.json"))
    lines = []
    for shot in sorted(statuses):
        st = statuses[shot]
        if st.get("file_relpath"):
            p = os.path.join(store, st["file_relpath"])
            # A file deleted locally after Aurora verification keeps its manifest line (hash from QA time).
            if os.path.exists(p) and os.path.getsize(p) != st["bytes"]:
                sys.exit("size mismatch, refusing to write manifest: " + p)
            lines.append("{}  {}".format(st["sha256"], st["file_relpath"]))
    # Status files in transfer/ are written once (open mode "x"); cache their hashes by (size, mtime).
    cache_path = os.path.join(WORK, "manifest_cache_{}.json".format(diag))
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    for shot in sorted(statuses):
        rel = "_status/{}.json".format(shot)
        p = os.path.join(store, rel)
        stt = os.stat(p)
        key = "{}:{}".format(stt.st_size, stt.st_mtime_ns)
        if cache.get(rel, [None])[0] != key:
            cache[rel] = [key, sha256_file(p)]
        lines.append("{}  {}".format(cache[rel][1], rel))
    with open(cache_path + ".tmp", "w") as f:
        json.dump(cache, f)
    os.replace(cache_path + ".tmp", cache_path)
    for rel in ("README.md", "FETCH_SUMMARY.json"):
        if os.path.exists(os.path.join(store, rel)):
            lines.append("{}  {}".format(sha256_file(os.path.join(store, rel)), rel))
    with open(os.path.join(store, "MANIFEST.sha256.tmp"), "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(os.path.join(store, "MANIFEST.sha256.tmp"), os.path.join(store, "MANIFEST.sha256"))
    print("MANIFEST: {} lines; FETCH_SUMMARY: {}".format(len(lines), json.dumps(summary["totals"])))


def summarize(diag, statuses):
    with ledger_locked() as (rows, _):
        led = [r for (d, _s), r in rows.items() if d == diag]
    per_list = collections.OrderedDict()
    for r in led:
        L = per_list.setdefault(r["list"], collections.Counter())
        L["target"] += 1
        L["state_" + r["state"]] += 1
    out = {"diagnostic": diag, "updated_utc": utcnow(), "per_list": {}, "totals": {}}
    for lst, c in per_list.items():
        sts = [s for s in statuses.values() if s.get("list") == lst]
        written = [s for s in sts if s.get("file_relpath")]
        ch_hist = collections.Counter(s["n_ok"] for s in written)
        secs = [s["seconds_amortized"] for s in written if s.get("seconds_amortized")]
        out["per_list"][lst] = {
            "target": c["target"],
            "in_transfer_written": len(written),
            "in_transfer_no_data": sum(1 for s in sts if s["state"] == "no_data"),
            "ledger_states": {k[6:]: v for k, v in sorted(c.items()) if k.startswith("state_")},
            "channels_per_written_shot": dict(sorted(ch_hist.items())),
            "bytes_written": sum(s["bytes"] for s in written),
            "fewer_than_expected": sorted(s["shot"] for s in written
                                          if s.get("expected_n_channels") and s["n_ok"] < s["expected_n_channels"]),
            "seconds_amortized_mean": round(sum(secs) / len(secs), 1) if secs else None,
        }
    out["totals"] = {
        "written": sum(v["in_transfer_written"] for v in out["per_list"].values()),
        "no_data": sum(v["in_transfer_no_data"] for v in out["per_list"].values()),
        "bytes": sum(v["bytes_written"] for v in out["per_list"].values()),
    }
    return out


if __name__ == "__main__":
    if sys.argv[1] == "rebuild":
        rebuild(sys.argv[2])
    else:
        promote(sys.argv[1], sys.argv[2], dry="--dry-run" in sys.argv)
