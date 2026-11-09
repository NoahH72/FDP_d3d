# Brief for AI agents fetching DIII-D data with this repo

You are helping the repo owner fetch DIII-D data through FDP on an ALCF machine. Read README.md and docs/01-07
before acting. The owner wants the data faithful and the work provable; ask before anything irreversible.

## Hard rules

1. **Never fetch on a login node.** Real fetches run in PBS jobs. A one-shot probe of one shot
   (`fdp_smoke.py`, `ptdata_index.py`, `probe_mds.py`) is the only exception; if a probe hangs, move it into PBS.
2. **Never print, copy, log or export the token**, never `export BEARER_TOKEN`, never run an interactive `fdp login`
   from a job or script. Only the owner logs in. If the token is short, give the owner the refresh command (docs/02)
   and wait.
3. **Check the token before submitting** (`python3 toolkit/token_status.py <walltime h + margin>`).
4. **Fetch only.** No trimming, filtering, resampling, filling. Any storage change needs a per-channel lossless proof
   (docs/06) and the owner's agreement.
5. **Classify absent from the pinned index**, never from an exception (docs/04). Keep exact exception text.
6. **Smoke test, report, wait for a go-ahead, then bulk.** Report before fetching anything outside what was agreed.
7. **Never delete data** until the owner confirms the transfer finished and the checksum check passed.
8. **Go gently on GA**: measure lanes before scaling up; watch per-channel read time (docs/05).
9. Never edit a running driver script; one driver per campaign; kill by exact PID on the same login node.

## Working pattern that worked

- Keep a campaign folder with an `OPEN_ITEMS.md` (decisions, open questions, the owner's words when they decide
  something) and a `TRANSFER_LOG.md` (what was submitted, changed, found, transferred, deleted, with UTC times).
- Status files are the ledger. Report states (fetched / no_data / error / not attempted), TB, rate, ETA, and what is
  waiting on the owner. Distinguish facts you checked from estimates.
- When numbers look odd, look at the per-shot status files before explaining them (for example, errors that look
  like outages were mostly single bad worker processes, docs/05).
- Before giving an ETA, measure the recent rate (slices per hour, shots per slice) and say what could move it.
- Record anything the data cannot tell you (for example probe geometry, physical identity of a channel family) as an
  open item, and remind the owner in reports.

## Typical tasks

| Task | Where |
|---|---|
| New site first session | docs/07 checklist, then selftest |
| New signal family | probe nodes/pointnames (docs/04), write a spec in toolkit/signals/, smoke test, report |
| Bulk run | docs/05: slices, driver, watch, retry pass, manifest, transfer |
| Worked example of a full campaign | examples/mirnov/ (smoke tests, reports, driver, promote, README writer) |
