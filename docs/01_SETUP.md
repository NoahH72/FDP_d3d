# 01 Setup

What you need once per machine (Polaris, Aurora) and per person.

## Access

- An ALCF account on the machine and membership in the project allocation (`-A <PROJECT>` in every qsub).
- A GitHub account that is a member of the **DIII-D** GitHub organization. FDP tokens are issued by the DIII-D Pelican
  issuer from your GitHub org membership (docs/02). Without the org, every read fails with `Error code 4000`.

## The two FDP environments

FDP is installed as a [pixi](https://pixi.sh) environment. Two are in use, and both specs are pinned in `env/`
(`pixi.toml` plus the exact `pixi.lock`):

| | `env/fdp-2026-11` (**new**; `env/fdp-2026-10` is the same without h5py) | `env/fdp-old-ptdata146` (**old**) |
|---|---|---|
| Versions | fdp-core 1.30.0: fdp 0.12.1, toksearch 2.19.0, toksearch_d3d 0.15.2, ptdata 2.11.5, pelican 7.26.3; plus h5py 3.16 (fdp-core alone has no h5py, which the toolkit needs) | toksearch 0+untagged.74, toksearch_d3d 0.4.0, ptdata 1.4.6 |
| Use for | **new signals** (CER, anything not fetched before) | continuing a store that was built with it (ECEI, BES, Mirnov), so new shots match old ones bit for bit |
| Launch | `fdp run --device d3d python script.py` | `$ENV/bin/fdp run $ENV/bin/python script.py` with `CONDA_PREFIX=$ENV PREFIX=$ENV LD_LIBRARY_PATH=$ENV/lib` |
| PTDATA index | handled by the package | the package hard-codes a **removed** snapshot; code must repoint `PTDATA_JSON_INDEX_DIR` (toolkit does it) |
| Numbers | calibrated values come back at float32 precision: up to 2e-7 relative from the old env | bit-identical to GA's own toksearch on saga (checked on 44 reference channels) |

`toolkit/site.sh` launches either one (`FDP_ENV_KIND=new|old`). On a new machine you only need the **new** env
unless you must extend an old-env store.

## Install

1. Install pixi (once). Either the official installer (`curl -fsSL https://pixi.sh/install.sh | bash`, needs internet
   on the login node) or conda: `module load conda; conda create -y -n fdp-installer -c conda-forge pixi`, then pixi is
   `~/.conda/envs/fdp-installer/bin/pixi` (Polaris used pixi 0.66.0 this way).
2. Fill in `sites/site.env` (copy `sites/polaris.env.example` or `sites/aurora.env.example`). `WORK_ROOT` is where the
   env and campaigns go, on the project filesystem (Eagle or Flare), not home.
3. Install **on a compute node** (pixi on a login node fails: "failed to spawn thread ... Resource temporarily unavailable"):
   ```bash
   qsub -A <PROJECT> -q debug -l filesystems=home:eagle -l select=1:system=polaris -o install.out \
        -v REPO=$PWD,ENV_NAME=fdp-2026-11,PIXI=<path to pixi> toolkit/install_env.pbs
   ```
   The job uses the site proxy, installs from the lock file (exact versions) and prints the package versions.
4. One-time FDP state in your home directory:
   - `~/.fdp/latest_index_snapshot` containing the snapshot name (`json_indexes_2026-06-23_15:20:51` as of 2026-11).
     The toolkit prefers `FDP_INDEX_SNAPSHOT` from `sites/site.env`, but other code reads this file.
   - For the old env only: `ln -s cache/d3d.token ~/.fdp/token` (the old env reads `~/.fdp/token`; a symlink keeps it in
     step with every renewal. Never replace it with a copy).
5. Log in (docs/02), then run `toolkit/selftest.pbs` (README quick start). Expected: 165920 and 185000 `fetched`
   (ip, EFIT01 ipmhd, Thomson Te); 177267 `error` because that shot has no data at all (ip absent from the index, EFIT01
   `TreeFOPENR`, Thomson `TreeNODATA`, ip canary fails). `TreeFOPENR` is deliberately kept as an error, not absent:
   the same text could come from a transient read failure.

## Where things live (per machine)

| Path | What |
|---|---|
| `$WORK_ROOT/fdp-2026-11/.pixi/envs/default` | new env |
| `~/.fdp/cache/d3d.token` | the current 24 h token (written by `fdp login`; never print it) |
| `~/.config/pelican/` | pelican's stored login (refresh token, about 30 days) |
| `~/.fdp/latest_index_snapshot` | PTDATA index snapshot name |
| `<repo>/sites/site.env` | your machine settings (untracked) |
