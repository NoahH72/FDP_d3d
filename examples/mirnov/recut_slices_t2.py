#!/usr/bin/env python3
"""Re-cut the unsubmitted part of the job 2 slice series with new sizes per era. Shot set and order are unchanged; the old
files are kept in work/slices_old_<date>/. Refuses if capacity has claimed a slice or the driver is within 1 of the start.
  python3 recut_slices_t2.py <first slice number> E5=700 E6=590 ...
"""
import glob
import os
import re
import shutil
import sys
import time

R = "/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10"
S = os.path.join(R, "work", "slices")
ERAS = [("E5", 162691, 174408), ("E6", 174409, 177975), ("E7", 177976, 198185), ("L1", 198186, 205533), ("L2", 205534, 207046)]


def main():
    first = int(sys.argv[1])
    sizes = dict(a.split("=") for a in sys.argv[2:])
    if glob.glob(os.path.join(S, "JC_s*.txt")):
        sys.exit("capacity has claimed slices; not re-cutting")
    nxt = int(open(os.path.join(R, "work", "chain_state_t2", "NEXT")).read())
    if nxt >= first:
        sys.exit("driver NEXT={} has reached first={}".format(nxt, first))
    old = sorted(f for f in glob.glob(os.path.join(S, "J2_s[0-9][0-9][0-9].txt"))
                 if int(re.search(r"_s(\d+)", f).group(1)) >= first)
    shots = [int(x) for f in old for x in open(f).read().split()]
    if shots != sorted(shots) or len(set(shots)) != len(shots):
        sys.exit("slices not ordered or have duplicates")
    new = []
    for era, a, b in ERAS:
        group = [s for s in shots if a <= s <= b]
        n = int(sizes[era])
        new += [group[i:i + n] for i in range(0, len(group), n)]
    if sorted(x for g in new for x in g) != shots:
        sys.exit("shot set changed; not re-cutting")
    keep = os.path.join(R, "work", "slices_old_" + time.strftime("%Y%m%d_%H%M"))
    os.makedirs(keep)
    tmp = []
    for i, g in enumerate(new):
        p = os.path.join(S, ".new_J2_s{:03d}.txt".format(first + i))
        with open(p, "w") as f:
            f.write("\n".join(map(str, g)) + "\n")
        tmp.append(p)
    for f in old:
        shutil.move(f, keep)
    for p in tmp:
        os.rename(p, os.path.join(S, os.path.basename(p)[5:]))
    print("re-cut {} shots: {} old slices -> {} new, s{:03d}-s{:03d}; old in {}".format(
        len(shots), len(old), len(new), first, first + len(new) - 1, keep))


if __name__ == "__main__":
    main()
