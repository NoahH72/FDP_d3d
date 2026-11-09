# FDP on DIII-D (ALCF Polaris and Aurora)

Fetch DIII-D data (PTDATA and MDSplus) on ALCF machines through the [Fusion Data Platform (FDP)](https://ga-fdp.github.io/)
and Pelican/OSDF, with no local PTDATA mirror. Everything here was used in production on Polaris through
2026-11 (ECEI, BES, Mirnov fetch campaigns, several TB each) and is written so that a person or an AI agent can
start a new fetch on Polaris or Aurora from a fresh clone.

**Status, 2026-11-08.** Polaris: working and in production. Aurora: not yet tried; follow
[docs/07_AURORA.md](docs/07_AURORA.md), which lists exactly what still has to be checked there.

## Start here

| You want to | Read |
|---|---|
| Set up a new machine or account | [docs/01_SETUP.md](docs/01_SETUP.md), then [docs/02_TOKENS.md](docs/02_TOKENS.md) and [docs/03_NETWORK.md](docs/03_NETWORK.md) |
| Fetch a new signal (CER, EFIT, Thomson, any pointname) | [docs/04_FETCHING.md](docs/04_FETCHING.md) |
| Fetch it for thousands of shots | [docs/05_CAMPAIGNS.md](docs/05_CAMPAIGNS.md) |
| Make sure the data are faithful and provable | [docs/06_DATA_INTEGRITY.md](docs/06_DATA_INTEGRITY.md) |
| Run on Aurora | [docs/07_AURORA.md](docs/07_AURORA.md) |
| You are an AI agent | [AGENTS.md](AGENTS.md) first |
| Something broke | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

## Quick start (any ALCF machine, after docs/01 setup)

```bash
git clone https://github.com/NoahH72/FDP_d3d.git && cd FDP_d3d
cp sites/polaris.env.example sites/site.env      # or sites/aurora.env.example; fill in the <...> values
python3 toolkit/token_status.py 2                # token must have storage.read and >= 2 h left (docs/02)

# end-to-end check on a compute node: token, proxy, PTDATA + MDSplus, index, toolkit fetch of 3 shots
qsub -A <PROJECT> -q debug -l filesystems=home:eagle -l select=1:system=polaris -o selftest.out \
     -v REPO=$PWD toolkit/selftest.pbs
```

Then fetch something: write a signal spec (see `toolkit/signals/`), run a smoke test on a handful of shots, check it,
and only then cut slices and start the chain driver (docs/05).

## The rules that matter most

1. **Never fetch on a login node.** Real fetches run in PBS jobs; a one-shot probe of a single shot is the only exception.
2. **Never print, copy or export the token** (`BEARER_TOKEN`). `fdp run` finds it. Only the account owner logs in.
3. **Check the token before every job**: a job keeps the token it started with, and tokens last 24 h.
4. **Pin the PTDATA index snapshot** and classify "absent" from the index, never from an exception (docs/04).
5. **Fetch only**: store records exactly as returned. No trimming, resampling or filling. Any storage change (such as
   float32) needs a per-channel proof that it is lossless (docs/06).
6. **Smoke test, then report, then bulk.** Identity-check against a reference where one exists.
7. **Go gently on GA.** More lanes slow every read; watch the per-channel read time (docs/05).

## Repository layout

```
FDP_d3d/
├── AGENTS.md          Brief for AI agents running fetches
├── docs/              Current guides (01-07); docs/legacy/ = the June 2026 guides (proxy/token steps outdated)
├── toolkit/           General fetch toolkit: fetch_signals.py, run_slice.pbs, chain_driver.sh, make_slices.py,
│                      manifest.py, ptdata_index.py, probe_mds.py, token_status.py, fdp_smoke.py, selftest.pbs
│   └── signals/       Signal spec examples (core_basic.json is verified)
├── sites/             Per-machine settings (*.env.example; your filled-in copy sites/site.env is untracked)
├── env/               pixi.toml + pixi.lock of both FDP environments (exact versions)
├── examples/mirnov/   The Mirnov campaign code (2026-10/11), a complete worked example of a production campaign
├── pipeline/ pbs/ submit/   ECEI pipeline (old env; Ray based)
├── bes/               BES pipeline (old env)
└── scripts/           Older utilities (login-node proxy, installer); superseded, kept for reference
```

## How it works

```
PBS job on a compute node
  └─ fdp run python fetch_signals.py          (fdp sets the token, MDSplus tree paths, PTDATA index)
       └─ toksearch / toksearch_d3d / ptdata  (PtDataSignal, MdsSignal)
            └─ XRootD + Pelican plugin  ──>  ALCF proxy (proxy.alcf.anl.gov:3128)
                 └─ Pelican/OSDF caches  ──>  DIII-D origin (PTDATA archives, MDSplus trees, PTDATA json index)
```

## Contact

- **Author:** Noah Harris (Oregon State University)
- **FDP and token questions:** GA FDP team, https://ga-fdp.github.io/
- **ALCF support:** support@alcf.anl.gov
