# 07 Aurora

Nothing in this repo has run on Aurora yet (2026-11-08). The toolkit is site-independent (all machine settings are in
`sites/site.env`), so the work is: install, log in, check the items below once, then fetch as on Polaris. Fetching
on Aurora writes straight to Flare, which saves the Polaris -> Aurora Globus step and Eagle quota.

## First session on Aurora (in this order; record what you find in `sites/aurora.env.example` and here)

1. **Clone** the repo to Flare: `/lus/flare/projects/<PROJECT>/<USER>/FDP_d3d`.
2. **Site file**: `cp sites/aurora.env.example sites/site.env`, fill in PROJECT and WORK_ROOT.
3. **Queues** (unverified): `qstat -Q`, and the ALCF Aurora queue documentation. Find the debug-type queue(s), node
   limits, per-user running/queued limits and walltimes; set `QUEUES` (`name:max_jobs_of_this_series`) and
   `WALLTIME`. Check `qsub -l filesystems=` names (expected `home:flare`) and whether `select=1` needs extra resources.
4. **pixi**: install it in home (docs/01). Aurora compute nodes are Intel Xeon (x86_64), so the `linux-64` lock file
   applies as is.
5. **Install the new env** on a compute node: `toolkit/install_env.pbs` with `ENV_NAME=fdp-2026-11`. If the login node
   has no direct internet, pixi itself also needs the proxy (unverified; the job sets it).
6. **Index snapshot file**: `mkdir -p ~/.fdp && echo json_indexes_2026-06-23_15:20:51 > ~/.fdp/latest_index_snapshot`.
7. **Token**: the account owner runs `fdp login --fresh --device d3d` on an Aurora login node (docs/02). Aurora has its
   own home, so its token is separate from Polaris's and needs its own daily refresh.
8. **Proxy** (unverified for FDP): `toolkit/selftest.pbs` tests it. ALCF documents `proxy.alcf.anl.gov:3128` for
   Aurora compute nodes.
9. **Selftest**: `qsub ... -v REPO=$PWD toolkit/selftest.pbs`. Expect 165920 and 185000 `fetched` (ip, EFIT01 ipmhd,
   ELECTRONS Thomson Te) and 177267 `error` with nothing fetchable (docs/01 step 5). If anything differs, stop and fix before fetching.
10. **Identity across sites**: fetch 2-3 shots of a signal Polaris already holds, with the same env, and compare the
    `sha256_data` values in the status files. Same env and same index snapshot should give identical bytes.
11. **Lanes**: Aurora nodes have more cores than Polaris (2 x 52-core Xeon Max). Do not scale lanes up blindly: start at
    16-32 lanes on one node, measure median good-shot seconds and the median per-channel read time, and keep the total
    across Polaris and Aurora gentle on GA (see docs/05; the Polaris campaigns used 2 nodes x 48 lanes).

## Coordinating two sites

- **Split by signal, not by shot**: one site per signal family avoids two stores of the same thing. (Plan as of
  2026-11: Mirnov stays on Polaris and is transferred with Globus; new families such as CER start on Aurora.)
- If both sites ever fetch the same family, use the same env, index snapshot and code, and different shot ranges.
- Watch the per-channel read time on both sites; if it climbs while the other site runs, lower lanes.

## Unverified on Aurora (update as you confirm)

| Item | Expected | Verified? |
|---|---|---|
| Proxy for compute nodes | `proxy.alcf.anl.gov:3128` | no |
| Queue names, limits | see ALCF docs | no |
| `-l filesystems=` value | `home:flare` | no |
| pixi install on a compute node | works with proxy | no |
| FDP token login on a login node | same as Polaris | no |
| selftest | 165920/185000 fetched, 177267 error (no data at all) | no (Polaris: old env passed 2026-11-08; new env rerun pending) |
