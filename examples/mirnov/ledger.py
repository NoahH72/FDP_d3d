#!/usr/bin/env python3
"""Ledger and slice management.

  ledger.py init                              create work/ledger.csv from the target lists (all 'todo'; idempotent)
  ledger.py assign CHUNK DIAG LIST MAXSHOT    put every unassigned shot of LIST with shot < MAXSHOT into CHUNK
  ledger.py slices CHUNK SIZE [STATES] [NAME]  write work/slices/NAME_sNNN.txt (NAME defaults to CHUNK) from CHUNK's
                                              shots in STATES (comma list, default todo,error), ascending
  ledger.py summary                           counts per diagnostic/list/chunk/state
"""
import collections
import os
import sys

from common import INPUTS, LISTS, SLICES, ledger_locked, read_shots, utcnow


def init():
    with ledger_locked() as (rows, save):
        n0 = len(rows)
        for diag, lst in LISTS:
            for s in read_shots(os.path.join(INPUTS, lst)):
                if (diag, s) in rows:
                    if rows[(diag, s)]["list"] != lst:
                        sys.exit("shot {} {} is in two lists".format(diag, s))
                    continue
                rows[(diag, s)] = {"diagnostic": diag, "list": lst, "shot": s, "chunk": "", "state": "todo",
                                   "n_channels": "", "n_listed": "", "bytes": "", "updated_utc": utcnow(), "note": ""}
        save()
        print("ledger rows: {} (added {})".format(len(rows), len(rows) - n0))


def assign(chunk, diag, lst, maxshot):
    with ledger_locked() as (rows, save):
        n = 0
        for r in rows.values():
            if r["diagnostic"] == diag and r["list"] == lst and not r["chunk"] and int(r["shot"]) < maxshot:
                r["chunk"] = chunk
                n += 1
        save()
    print("assigned {} shots to {}".format(n, chunk))


def slices(chunk, size, states=("todo", "error"), name=None):
    name = name or chunk
    with ledger_locked() as (rows, _):
        todo = sorted(int(r["shot"]) for r in rows.values() if r["chunk"] == chunk and r["state"] in states)
    os.makedirs(SLICES, exist_ok=True)
    paths = []
    for i in range(0, len(todo), size):
        p = os.path.join(SLICES, "{}_s{:03d}.txt".format(name, i // size + 1))
        if os.path.exists(p):
            sys.exit("slice file exists, refusing to overwrite: " + p)
        with open(p, "w") as f:
            f.write("\n".join(map(str, todo[i:i + size])) + "\n")
        paths.append(p)
    print("{} shots -> {} slices".format(len(todo), len(paths)))
    for p in paths:
        print(p)


def summary():
    with ledger_locked() as (rows, _):
        c = collections.Counter((r["diagnostic"], r["list"], r["chunk"] or "-", r["state"]) for r in rows.values())
    for k in sorted(c):
        print("{:5s} {:45s} {:5s} {:13s} {}".format(*k, c[k]))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "init":
        init()
    elif cmd == "assign":
        assign(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
    elif cmd == "slices":
        st = tuple(sys.argv[4].split(",")) if len(sys.argv) > 4 else ("todo", "error")
        slices(sys.argv[2], int(sys.argv[3]), st, sys.argv[5] if len(sys.argv) > 5 else None)
    elif cmd == "summary":
        summary()
    else:
        sys.exit("unknown command")
