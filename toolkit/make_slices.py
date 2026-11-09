#!/usr/bin/env python3
"""Cut slice files for a campaign from a shot list and the store's status files (the status files are the ledger).

    python3 make_slices.py --shots shots.txt --out STORE --slices CAMPAIGN/slices --series cer --size 400
           [--states todo,error,not_attempted] [--start 1]

A shot is `todo` when it has no status file. Shots in states fetched/no_data are never re-cut. Writes
<series>_s001.txt, s002, ... (numbering from --start) and refuses to overwrite an existing slice file, so a retry
pass uses --start after the last slice of the first pass. Prints the counts per state.
"""
import argparse
import collections
import json
import os


def state(out, shot):
    p = os.path.join(out, "_status", "{}.json".format(shot))
    if not os.path.exists(p):
        return "todo"
    try:
        return json.load(open(p)).get("state", "error")
    except ValueError:
        return "error"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--slices", required=True)
    ap.add_argument("--series", required=True)
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--states", default="todo,error,not_attempted")
    ap.add_argument("--start", type=int, default=1)
    a = ap.parse_args()
    shots = [int(l.split()[0]) for l in open(a.shots) if l.strip() and not l.startswith("#")]
    st = {s: state(a.out, s) for s in shots}
    print("states:", dict(collections.Counter(st.values())))
    want = set(a.states.split(","))
    pick = [s for s in shots if st[s] in want]
    os.makedirs(a.slices, exist_ok=True)
    chunks = [pick[i:i + a.size] for i in range(0, len(pick), a.size)]
    names = [os.path.join(a.slices, "{}_s{:03d}.txt".format(a.series, a.start + i)) for i in range(len(chunks))]
    clash = [n for n in names if os.path.exists(n)]
    if clash:
        raise SystemExit("refusing to overwrite {} (use --start after the last slice)".format(clash[0]))
    for n, c in zip(names, chunks):
        with open(n, "w") as f:
            f.write("\n".join(map(str, c)) + "\n")
    print("wrote {} slices of up to {} shots ({} shots): {} .. {}".format(len(chunks), a.size, len(pick),
          os.path.basename(names[0]) if names else "-", os.path.basename(names[-1]) if names else "-"))


if __name__ == "__main__":
    main()
