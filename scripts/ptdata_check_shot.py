#!/usr/bin/env python3
"""Run ptdata.check with a configurable shot (default 142170).

Use the FDP pixi interpreter, and on Polaris compute nodes set e.g.:

  export CONDA_PREFIX=$FDP_ROOT/.pixi/envs/default
  export PREFIX="$CONDA_PREFIX"
  export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1

  PTDATA_CHECK_SHOT=142170 \\
    $FDP_ROOT/.pixi/envs/default/bin/fdp run \\
    $FDP_ROOT/.pixi/envs/default/bin/python \\
    /path/to/FDP_d3d/scripts/ptdata_check_shot.py

Optional: PTDATA_CHECK_POINTNAME=IP (default IP).
Pelican auth: BEARER_TOKEN or ~/.fdp/token (see ptdata package docs).
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    import ptdata.check as chk

    chk.CHECK_SHOT = int(os.environ.get("PTDATA_CHECK_SHOT", "142170"))
    chk.CHECK_POINTNAME = os.environ.get("PTDATA_CHECK_POINTNAME", "IP")
    chk.main()


if __name__ == "__main__":
    main()
