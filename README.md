# FDP on DIII-D (Polaris)

Fetch DIII-D diagnostic data (ECEI, BES, physics signals) on [ALCF Polaris](https://www.alcf.anl.gov/polaris) using the [Fusion Data Platform (FDP)](https://ga-fdp.github.io/) and Pelican/OSDF remote access -- no local PTDATA mirror required.

## Quick Start

If you already have a Polaris account, an `<YOUR_PROJECT>` allocation, and a valid FDP bearer token, these five steps get you from zero to your first ECEI data fetch:

```bash
# 1. Clone this repo on Polaris
git clone https://github.com/NoahH72/FDP_d3d.git
cd FDP_d3d

# 2. Install the FDP pixi environment (run on an interactive compute node)
qsub -I -q debug -l select=1:ncpus=4:mem=32gb,walltime=01:00:00,filesystems=eagle -A <YOUR_PROJECT>
bash scripts/install_fdp_polaris.sh
exit   # back to login node

# 3. Start the HTTPS proxy on the login node
screen -dmS fdp_proxy python3 scripts/https_proxy.py --port 18443

# 4. Verify your bearer token
cat ~/.fdp/token | head -c 40   # should show a JWT string

# 5. Submit a 2-shot smoke test
mkdir -p ~/pbs
qsub -A <YOUR_PROJECT> \
  -q debug \
  -l select=1:ncpus=4:mem=32gb,walltime=01:00:00,filesystems=eagle \
  -v BATCH_START=0,BATCH_END=2 \
  pbs/run_batch_channelwise.pbs
```

Monitor with `tail -f ~/pbs/ecei_channelwise.out`. You should see `Proxy reachable` followed by data processing output.

## Prerequisites

Before starting, you need:

- An [ALCF account](https://accounts.alcf.anl.gov/) with access to Polaris
- Membership in the `<YOUR_PROJECT>` project allocation
- A valid FDP bearer token (see [Prerequisites guide](docs/01_PREREQUISITES.md))
- Basic familiarity with SSH, command line, and PBS job submission

## Documentation

Step-by-step guides, in order:

| Guide | Description |
|-------|-------------|
| [01 - Prerequisites](docs/01_PREREQUISITES.md) | Polaris account, project allocation, FDP bearer token |
| [02 - Installation](docs/02_INSTALLATION.md) | Installing the FDP pixi environment on Polaris |
| [03 - Proxy Setup](docs/03_PROXY_SETUP.md) | HTTPS proxy for routing compute node traffic |
| [04 - Running ECEI Pipeline](docs/04_RUNNING_ECEI_PIPELINE.md) | Submitting ECEI batch jobs end-to-end |
| [05 - Running BES Pipeline](docs/05_RUNNING_BES_PIPELINE.md) | Standalone 64-channel BES data fetch |
| [06 - Interactive Debugging](docs/06_INTERACTIVE_DEBUG.md) | Hands-on debugging on a compute node |
| [07 - Monitoring and QA](docs/07_MONITORING_AND_QA.md) | Job monitoring, output validation, re-running failed shots |
| [08 - Architecture](docs/08_ARCHITECTURE.md) | System design, data flow, environment variables |
| [09 - Performance](docs/09_PERFORMANCE.md) | Benchmarks, scaling projections, optimization details |

## Reference

| Document | Description |
|----------|-------------|
| [Troubleshooting](TROUBLESHOOTING.md) | Symptom-cause-fix lookup table |
| [Issues and Future Work](ISSUES_AND_FUTURE_WORK.md) | Known issues, resolved blockers, planned improvements |
| [Changelog](CHANGELOG.md) | Timeline of major fixes and milestones |

## Repository Layout

```
FDP_d3d/
├── docs/           Step-by-step guides (start here)
├── scripts/        Utility scripts (installer, proxy, checks)
├── pipeline/       ECEI data fetch pipeline code
├── pbs/            PBS job scripts for Polaris
├── submit/         Job submission helpers
├── bes/            BES standalone fetch pipeline
└── env/            Environment specs (pixi.toml, env templates)
```

## How It Works

FDP uses [Pelican/OSDF](https://pelicanplatform.org/) to serve DIII-D PTDATA archives over HTTPS from a CDN. On Polaris, compute nodes lack direct internet access, so a lightweight HTTP CONNECT proxy runs on a login node and routes XRootD/Pelican traffic from compute nodes transparently. The pipeline uses [TokSearch](https://diii-d.gat.com/diii-d/TokSearch) with Ray for parallel data extraction across shots.

```
Compute Node (Ray workers)
  --> ptdata64 C extension
    --> XRootD + Pelican plugin
      --> HTTP CONNECT proxy (login node, port 18443)
        --> Pelican CDN (osg-htc.org, ESnet 100 Gb/s)
          --> DIII-D origin server
```

## Contact

- **Author:** Noah Harris (Oregon State University)
- **FDP/Token questions:** Brian (GA-FDP team) -- [request a token](https://forms.office.com/g/wEaBDGqqq8)
- **ALCF support:** [support@alcf.anl.gov](mailto:support@alcf.anl.gov)
