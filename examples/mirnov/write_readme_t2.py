#!/usr/bin/env python3
"""Write transfer/Mirnov_T2_MPI_D/README.md. Rerun after each promote; promote.py rebuild then re-hashes it."""
import hashlib
import json
import os

from common import INPUTS, ROOT, STORE, WORK, utcnow


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    store = STORE["T2"]
    summ = json.load(open(os.path.join(store, "FETCH_SUMMARY.json"))) if os.path.exists(os.path.join(store, "FETCH_SUMMARY.json")) else {}
    code = {f: sha(os.path.join(ROOT, "code", f)) for f in ("mirnov_fetch_t2.py", "run_slice_t2.pbs", "chain_driver_t2.sh", "run_cap_t2.pbs", "cap_worker_t2.sh", "promote.py")}
    smoke = open(os.path.join(WORK, "SMOKE_REPORT_T2.md")).read()
    out = ["""# Mirnov_T2_MPI_D: DIII-D magnetic probes dB/dt (all MPI*D except MPI66M###D), raw PTDATA

Job 2 of the Mirnov fetch (saga HANDOFF 2026-10-20): tier 2 minus tier 1. Every `MPI*D` pointname except the toroidal
midplane `MPI66M###D`, which is in the companion store `Mirnov_T1_MPI66M`, for the shots in `shots_mirnov_tier2.txt`
(52,143 shots, the same list as tier 1). 38-39 channels per shot before 152129, 50-62 after. Updated {}. Produced on
ALCF Polaris by `mirnov_2026-10/`.

**Fetch only.** Full records exactly as PTDATA returns them: no trimming, filtering, resampling, alignment or filling.
A channel the archive does not hold is absent from the file and marked `absent` in `_status/<shot>.json`.

## Layout

`<shot//1000>xxx/<shot>.h5`, one file per shot:
- `/<POINTNAME>/data`: the calibrated values (PTDATA `ical=1`), **float32** where the per-channel lossless check passed
  (attribute `float32_lossless`), float64 otherwise; gzip-4, no shuffle.
- `/timebases/tbN`: each distinct time base once, float64 ms, exactly as returned; channel attribute `timebase`
  names its array. `t_first_ms`, `dt_nominal_ms`, `sample_rate_hz_nominal`, `n_samples` are given for convenience.
- Channel attributes also hold the PTDATA header as returned (`ptdata_*`), `units_returned`, `burst_record` (131,072-sample
  bursts before 149581: every probe here except `MPI11M322D`), and `position_token_from_name` plus
  `toroidal_angle_deg_from_name` (parsed from the pointname, **not** from a geometry file).
- Root attributes: shot, channel list, per-shot `sample_rate_hz` (or -1 when channels differ) and `sample_rates_hz`.

## Why float32 is lossless here

The archive stores integer ADC counts (12-bit before 149581, 16-bit after). For every stored channel the fetcher checks
that float32 keeps every distinct returned value distinct and in order, with rounding below 0.01 of the smallest count
step (a count stays exactly recoverable below 0.5). On a sample of shots (`shot % 20 == 0`) it also re-fetches the raw
counts and checks the count -> value map is one-to-one. Smoke test: 727/727 channels passed, worst rounding 0.0024 of
a step.

## Route, identity, versions

FDP (Pelican/OSDF) via the ALCF proxy, old FDP env `/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/fdp/` (toksearch 0+untagged.74,
toksearch_d3d 0.4.0, ptdata 1.4.6 - the env that built the BES/ECEI stores), PTDATA json index snapshot
`json_indexes_2026-06-23_15:20:51`. Identity: the saga reference channels (toksearch/athena, 2026-10-20) are
bit-identical (data and times) on 9/9 smoke comparisons (`MPI1A322D` on 8 shots, `MPI1A026D` on 206661).
The newer ptdata 2.11.5 differs from saga by <= 2e-7 relative and was not used. Code sha256: `{}`.

## Absent vs error

FDP reports an absent pointname and a shot with no PTDATA with the same exception, so each channel is classified from
the PTDATA index: `ok` (listed, fetched, QA passed), `absent` (not listed), `error` (listed, fetch or QA failed; exact
exception text). Shots with nothing listed have state `no_data` and an `ip` canary result.

## Open item (not in this store)

Probe (R, Z) / poloidal position, orientation and digitizer are not in PTDATA. They need an authoritative DIII-D
magnetics geometry source and can be added later as attributes without refetching (see `OPEN_ITEMS.md` G1).

## Source lists

Saga bundle `inputs/` with `SHA256SUMS`:

```
{}
```

## Counts

```
{}
```

## Smoke test (2026-11-06)

""".format(utcnow(), json.dumps(code), open(os.path.join(INPUTS, "SHA256SUMS")).read().strip(),
           json.dumps(summ.get("per_list", {}), indent=1))]
    out.append(smoke.split("\n", 1)[1])
    rep = os.path.join(WORK, "FINAL_REPORT_T2.md")
    if os.path.exists(rep):
        out.append("\n## Final fetch report\n")
        out.append(open(rep).read().split("\n", 1)[1])
    with open(os.path.join(store, "README.md.tmp"), "w") as f:
        f.write("\n".join(out))
    os.replace(os.path.join(store, "README.md.tmp"), os.path.join(store, "README.md"))
    print("wrote", os.path.join(store, "README.md"))


if __name__ == "__main__":
    main()
