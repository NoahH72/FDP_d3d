# Issues and future work

## Open

1. **Aurora not yet tried.** Checklist and unverified items in docs/07.
2. **Lanes vs GA load.** Per-channel read time grows with lanes (2.05 s at 32, 2.6 s at 48, 3.15 s at 64 per Polaris
   node). Not known whether that is node-side or GA-side. Measure on Aurora; keep the two-site total gentle.
3. **Bad worker processes.** Occasionally one worker (rarely up to 5) fails every shot it takes with `Cannot open file`
   on the index json until it recovers or the job ends. Harmless to the data (state error, retried) but it inflates
   retry passes. A possible fix (recycle a worker after N consecutive all-signal failures) was not tried mid-campaign.
4. **Probe geometry and channel identity are not in PTDATA.** Mirnov stores hold only what the archive provides plus
   the toroidal angle parsed from the pointname; probe (R, Z), orientation and digitizer need an authoritative DIII-D
   magnetics geometry source (EFIT probe list or the magnetics machine description). Same for the physical identity
   of `B1`-`B8`.
5. **MDS absence is inferred from error text** (`TreeNNF`/`TreeNODATA`), because MDSplus has no index over FDP.
   Status files keep the text and mark `absent_basis`.
6. **Index snapshot age.** Campaigns are pinned to `json_indexes_2026-06-23_15:20:51`; newer shots need a newer
   snapshot. Moving a campaign to a new snapshot should be a deliberate, recorded decision.
7. **Login-node limits.** Thread limits make pixi and live fetches fail on login nodes; everything heavy runs in PBS.

## Resolved (2026-04 to 2026-11)

- Tokens: 1-month manual tokens replaced by 24 h tokens from `fdp login` with a pelican refresh token (2026-10).
- Proxy: login-node `screen` proxy replaced by the ALCF proxy (2026-10).
- Removed PTDATA index snapshot hard-coded in the old fdp package: repointed in all code (2026-07 / 2026-10).
- Absent vs error: classified from the pinned index (2026-10).
- Driver lock and heartbeat for multi-login-node sessions; background promote (2026-10/11).
- XRootD plugin symlinks, `ALL_PROXY` vs `https_proxy`, Ray API and temp-dir issues (2026-04, see CHANGELOG).

## Future

- [ ] Verify Aurora and record queue/proxy facts in docs/07.
- [ ] Verified CER signal spec (IONS tree) and a CER smoke test.
- [ ] Worker recycling for bad workers (issue 3).
- [ ] Store-level README writer in the toolkit (examples/mirnov/write_readme_t2.py is the model).
- [ ] Unit tests for fetch_signals.py classification logic with stubbed toksearch.
