"""Shared paths, list loading and ledger I/O for the addendum 2026-10 pass (stdlib only)."""
import csv
import fcntl
import hashlib
import os
import time
from contextlib import contextmanager

ROOT = "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10"
INPUTS = os.path.join(ROOT, "inputs")
WORK = os.path.join(ROOT, "work")
LEDGER = os.path.join(WORK, "ledger.csv")
SLICES = os.path.join(WORK, "slices")
STAGING = {"T1": os.path.join(WORK, "staging", "T1"), "T2": os.path.join(WORK, "staging", "T2")}
STORE = {"T1": os.path.join(ROOT, "transfer", "Mirnov_T1_MPI66M"), "T2": os.path.join(ROOT, "transfer", "Mirnov_T2_MPI_D")}
LISTS = [  # (diagnostic, list file) in processing order
    ("T1", "shots_mirnov_tier1.txt"),
    ("T2", "shots_mirnov_tier2.txt"),
]
LEDGER_FIELDS = ["diagnostic", "list", "shot", "chunk", "state", "n_channels", "n_listed",
                 "bytes", "updated_utc", "note"]
STATES = ("todo", "fetched", "no_data", "error", "promoted", "on_aurora", "local_deleted", "skipped")


def read_shots(path):
    with open(path) as f:
        return [int(l.split()[0]) for l in f if l.strip()]


def h5_path(diag, root, shot):
    return os.path.join(root, "{}xxx".format(shot // 1000), "{}.h5".format(shot))


def rel_h5(diag, shot):
    return os.path.relpath(h5_path(diag, "/", shot), "/")


def utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(path, bufsize=1 << 24):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(bufsize), b""):
            h.update(b)
    return h.hexdigest()


@contextmanager
def ledger_locked():
    """Yield (rows, save). rows is a dict keyed by (diagnostic, shot). Exclusive lock for the duration."""
    lock = open(LEDGER + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        rows = {}
        if os.path.exists(LEDGER):
            with open(LEDGER) as f:
                for r in csv.DictReader(f):
                    rows[(r["diagnostic"], int(r["shot"]))] = r

        def save():
            tmp = LEDGER + ".tmp"
            with open(tmp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
                w.writeheader()
                order = {(d, l): i for i, (d, l) in enumerate(LISTS)}
                for r in sorted(rows.values(), key=lambda r: (order[(r["diagnostic"], r["list"])], int(r["shot"]))):
                    w.writerow(r)
            os.replace(tmp, LEDGER)

        yield rows, save
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def ledger_update(diag, shot, **fields):
    with ledger_locked() as (rows, save):
        r = rows[(diag, int(shot))]
        for k, v in fields.items():
            r[k] = "" if v is None else str(v)
        r["updated_utc"] = utcnow()
        save()
