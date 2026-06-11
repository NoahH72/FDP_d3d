"""
Scheduler-aware CPU limits for Ray pipelines (SLURM and PBS).
Used by run_ecei_download and run_physics_download to avoid oversubscription
on login nodes and to cap physics workers (large memory per shot).
"""
import os


def _is_batch_job():
    """True when running inside a SLURM or PBS allocation."""
    return "SLURM_JOB_ID" in os.environ or "PBS_JOBID" in os.environ


def get_allowed_cpus():
    """
    Returns the number of CPUs to use for Ray (e.g. ECEI pipeline).
    - Login node (no batch job env): low default 4 to be polite.
    - In a SLURM job: prefer SLURM_CPUS_PER_TASK / SLURM_JOB_CPUS_PER_NODE.
    - In a PBS job: prefer NCPUS (set by PBS on Polaris).
    - Fallback: sched_getaffinity.
    """
    if not _is_batch_job():
        return 4

    for var in (
        "SLURM_CPUS_PER_TASK",
        "SLURM_JOB_CPUS_PER_NODE",
        "SLURM_CPUS_ON_NODE",
        "NCPUS",
    ):
        n = os.environ.get(var)
        if n is not None:
            try:
                return max(1, int(n))
            except ValueError:
                pass
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return 4


# Max CPUs for physics pipeline even when Slurm gives more.
# Default 14 matches profile ~7.5 GB/shot on 180 GB (80% usable). Override with PHYSICS_MAX_CPUS if needed.
# Tune after running: python profile_physics_extras_memory.py [--group all|ptdata|mds]
_PHYSICS_MAX_CPUS = 14

# MDS-only pass (BCI, Filterscope, Thomson, EFIT extra) is memory-light; allow more workers.
_PHYSICS_MDS_MAX_CPUS = 20


def get_physics_allowed_cpus():
    """
    Returns the number of CPUs for the physics pipeline (PTDATA-heavy or full fusion-fm).
    Caps at _PHYSICS_MAX_CPUS so N * ~7.5 GB per shot fits on typical nodes.
    Override with env PHYSICS_MAX_CPUS (e.g. 19 for 180G).
    """
    cap = _PHYSICS_MAX_CPUS
    env_cap = os.environ.get("PHYSICS_MAX_CPUS")
    if env_cap is not None:
        try:
            cap = max(1, int(env_cap))
        except ValueError:
            pass
    return min(get_allowed_cpus(), cap)


def get_physics_mds_allowed_cpus():
    """
    Returns the number of CPUs for the MDS-only fusion-fm pass (BCI, Filterscope, Thomson, EFIT).
    MDS pass is memory-light; cap at _PHYSICS_MDS_MAX_CPUS. Override with PHYSICS_MDS_MAX_CPUS.
    """
    cap = _PHYSICS_MDS_MAX_CPUS
    env_cap = os.environ.get("PHYSICS_MDS_MAX_CPUS")
    if env_cap is not None:
        try:
            cap = max(1, int(env_cap))
        except ValueError:
            pass
    return min(get_allowed_cpus(), cap)


# Cap assembly workers: streaming assembly uses ~tens MB per worker.
# With 384 GB on saga07: 24 workers is a safe bump for testing.
_ASSEMBLY_MAX_CPUS = 24


def get_assembly_allowed_cpus():
    """
    Returns the number of CPUs for the assembly pipeline.
    Caps at _ASSEMBLY_MAX_CPUS; assembly uses ~7 GB per shot, so worker count
    must fit in job memory (e.g. 64 GB -> 6 workers).
    """
    return min(get_allowed_cpus(), _ASSEMBLY_MAX_CPUS)
