#!/bin/bash
# Complete FDP (pixi) install on Polaris. Run from a normal login shell or an
# interactive PBS job if `pixi install` fails with "Resource temporarily unavailable".
#
# Interactive fallback (1 hour, Eagle):
#   qsub -I -q debug -l select=1:ncpus=4:mem=32gb,walltime=01:00:00,filesystems=eagle
#   bash /path/to/FDP_d3d/scripts/install_fdp_polaris.sh
#
set -euo pipefail
export RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-2}"
export TOKIO_WORKER_THREADS="${TOKIO_WORKER_THREADS:-2}"

module use /soft/modulefiles 2>/dev/null || true
module load conda
source "$(conda info --base)/etc/profile.d/conda.sh"

if ! conda env list | grep -q '^fdp-installer '; then
  echo "Creating fdp-installer env..."
  conda create -y -c ga-fdp -c conda-forge -n fdp-installer "fdp-installer>=0.5.0"
fi
conda activate fdp-installer

# FDP_DIR: where the pixi environment is installed.
# Override by setting FDP_DIR before running this script.
FDP_DIR="${FDP_DIR:-$HOME/fdp-env}"
mkdir -p "$FDP_DIR"

if [[ ! -f "$FDP_DIR/pixi.toml" ]]; then
  echo "Running fdp-install (copies pixi.toml)..."
  fdp-install --directory "$FDP_DIR"
fi

cd "$FDP_DIR"
echo "Running pixi install (this can take several minutes)..."
pixi install --concurrent-downloads "${PIXI_CONCURRENT_DOWNLOADS:-4}"

PY="$FDP_DIR/.pixi/envs/default/bin/python"
if [[ -x "$PY" ]]; then
  echo "Smoke test:"
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 "$PY" -c "import toksearch; import numba; import h5py; print('FDP env OK')"
else
  echo "WARNING: expected interpreter missing: $PY"
  exit 1
fi
echo "Done. PBS scripts will use this env when $PY exists."
