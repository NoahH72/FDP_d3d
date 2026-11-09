#!/usr/bin/env python3
"""Summarize a store from its status files and write MANIFEST.sha256 + SUMMARY.json (stdlib only, login-node safe).

    python3 manifest.py STORE [--quiet]

MANIFEST.sha256 lists `sha256  relpath` for every written .h5 (hashes recorded at write time by fetch_signals.py)
and every status file, in sha256sum format, so the receiving site can run `sha256sum -c MANIFEST.sha256` after a
transfer. SUMMARY.json has counts per state, bytes, and the per-signal ok/absent/error totals.
"""
import collections
import hashlib
import json
import os
import sys
import time


def main():
    store = sys.argv[1]
    sd = os.path.join(store, "_status")
    states, sig, nbytes, lines = collections.Counter(), collections.defaultdict(collections.Counter), 0, []
    for fn in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
        if not fn.endswith(".json"):
            continue
        p = os.path.join(sd, fn)
        st = json.load(open(p))
        states[st.get("state")] += 1
        for name, c in (st.get("signals") or {}).items():
            sig[name][c.get("status")] += 1
        if st.get("file_written") and st.get("sha256"):
            if os.path.exists(os.path.join(store, st["file_relpath"])):
                lines.append("{}  {}".format(st["sha256"], st["file_relpath"]))
                nbytes += st.get("bytes", 0)
        lines.append("{}  {}".format(hashlib.sha256(open(p, "rb").read()).hexdigest(), os.path.join("_status", fn)))
    with open(os.path.join(store, "MANIFEST.sha256.tmp"), "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(os.path.join(store, "MANIFEST.sha256.tmp"), os.path.join(store, "MANIFEST.sha256"))
    summ = {"updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "states": dict(states),
            "bytes": nbytes, "TB": round(nbytes / 1e12, 3), "signals": {k: dict(v) for k, v in sorted(sig.items())}}
    json.dump(summ, open(os.path.join(store, "SUMMARY.json"), "w"), indent=1)
    if "--quiet" not in sys.argv:
        print(json.dumps({k: summ[k] for k in ("states", "TB")}))


if __name__ == "__main__":
    main()
