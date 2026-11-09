# 06 Data integrity

The stores are used for physics and ML work, so every one has to be faithful to the archive and provably so.

## Fetch only

Store records exactly as returned: full time range, every sample, no trimming, filtering, resampling, alignment or
filling. A channel the archive does not hold is recorded `absent`, not filled. Anything you change about storage
must be proven lossless per channel (below), and recorded in the file.

## Identity checks

- If a reference exists (data fetched another way, e.g. on GA's saga cluster with toksearch against athena), compare
  sha256 of the data (cast to little-endian float32 or float64) and of the times (float64) for each reference channel.
  Equal hashes = the route is bit-identical. Mirnov: the old env matched 44/44 saga channels bit for bit; the new env
  differs by up to 2e-7 relative (it returns calibrated values at float32 precision), so stores continue on the env they
  started with.
- If there is no reference, compare the new env against the old env on a few shots; differences beyond float32 rounding
  mean something is wrong.
- fetch_signals.py records sha256 of the returned data per signal and of each written file, the code hash, package
  versions, host, pid and index snapshot in every status file.

## float32 storage (when, and how to prove it)

PTDATA holds integer ADC counts; calibrated values are an affine map of the counts. float32 is lossless for a channel
when float32 keeps every distinct returned value distinct and in order, with rounding well below the smallest value step
(the stores use < 0.01 step, so each count stays exactly recoverable; < 0.5 would already suffice). Stronger check used
for Mirnov on a sample (`shot % 20 == 0`): re-fetch raw counts (`ical=0`) and confirm the count -> value map is
one-to-one and the raw times equal the data times. Mirnov smoke: 727/727 channels lossless, worst rounding 0.0024 of a
step. Channels that fail stay float64 and are flagged. `--float32-checked` in the toolkit applies the first check.

## Time bases

- Times come back as float64 ms. They are **not** exactly `t0 + i*dt` (errors around 1e-12 ms), so store the array, not
  t0/dt, unless you prove it rebuilds exactly.
- Some records have multiple clocks (MPID 8 segments with different dt); never take the rate from the header.
- Some headers have nonsense start times (Mirnov: 125432, 130006 at 1e8 s; 169833 at 122.9 s): store as returned, flag.
- Broken time bases (non-monotonic) are archive defects: not stored, reported (docs/05).

## Absent vs error vs no_data

Classify from the pinned index, never from exceptions (docs/04). Keep the exact exception text for every error.
`no_data` shots get an `ip` canary result in their status.

## Provenance to keep with every store

README in the store: what, which shots, route and versions, index snapshot, code sha256, identity results, counts per
state, known defects and open items (for example probe geometry, which PTDATA does not hold). Keep the smoke report.
MANIFEST.sha256 for the transfer check.
