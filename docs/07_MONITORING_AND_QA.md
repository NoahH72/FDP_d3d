# 07 - Monitoring and QA

## Goal

Monitor running jobs, validate output data, and re-run failed or missing shots.

## Prerequisites

- At least one job submitted per [04 - Running ECEI Pipeline](04_RUNNING_ECEI_PIPELINE.md) or [05 - Running BES Pipeline](05_RUNNING_BES_PIPELINE.md)

---

## 1. Monitoring Jobs

### Check job status

```bash
qstat -u $USER
```

### Watch live output

```bash
tail -f ~/pbs/ecei_channelwise.out
```

### Watch live errors

```bash
tail -f ~/pbs/ecei_channelwise.err
```

### Per-node logs (multi-node jobs)

For multi-node jobs, each node writes its own log file. List them with:

```bash
ls ~/pbs/ecei_node*.log
```

### Key log lines indicating healthy operation

Look for these lines in the output to confirm things are working:

```
Proxy reachable: https://osg-htc.org via http://...
```

The proxy tunnel is up and the compute node can reach the Pelican CDN.

```
Using FDP remote data access via fdp run wrapper
```

The pipeline is using the FDP pixi environment and remote data access.

```
Done. N shots (4 passes) in ...
```

The batch completed successfully. `N` is the number of shots processed in that batch.

### Performance summary

Pull the most recent timing and status lines from the output log:

```bash
grep -E "Done\.|s/shot|shots OK|shots MISSING" ~/pbs/ecei_channelwise.out | tail -10
```

---

## 2. Validating Output Files

### Count completed shots

```bash
ls /eagle/fusiondl_aesp/harrisn/signal_data/ECEI_Assembled/*.h5 | wc -l
```

### Check a specific shot file structure

```python
import h5py

f = h5py.File('/eagle/fusiondl_aesp/harrisn/signal_data/ECEI_Assembled/142095.h5', 'r')
sig = f['2D']['ecei']['signal']
print('shape:', sig.shape)    # expected: (T, 20, 8)
print('dtype:', sig.dtype)    # expected: float32 or float64
print('freq:', f['2D']['ecei']['freq'][()])
f.close()
```

### Automatic post-loop validation

The pipeline runs post-loop validation automatically after each batch completes. It performs three checks:

1. Verifies the output HDF5 file exists on disk.
2. Calls `ecei_io.check_assembled_file()` to validate internal structure.
3. Confirms that `channel_means` has no all-zero rows.

### Known warning

```
all-zero channel_means rows 5-19
```

This may appear for older shots. It is a validation edge case, not a data error. The affected shots still contain valid signal data.

---

## 3. Finding Missing Shots

Use this script to compare your shot list against the output directory and identify any shots that were not fetched:

```python
import os
import numpy as np

shot_list = np.loadtxt(
    '/eagle/fusiondl_aesp/harrisn/shot_lists/Current_labeled_dset_highest_tol.txt'
)[:,0].astype(int)
out_dir = '/eagle/fusiondl_aesp/harrisn/signal_data/ECEI_Assembled'

missing = [s for s in shot_list if not os.path.exists(f'{out_dir}/{s}.h5')]
print(f'{len(missing)} / {len(shot_list)} shots missing')
if missing:
    print('First 10:', missing[:10])
```

---

## 4. Re-Running Failed or Missing Shots

The pipeline is **idempotent** -- it skips shots that already have a valid `.h5` file in the output directory. This means:

- Simply resubmit the same batch range. Only missing shots will be processed.
- To force a re-fetch of a specific shot, delete its `.h5` file first:

```bash
rm /eagle/fusiondl_aesp/harrisn/signal_data/ECEI_Assembled/<SHOT_NUMBER>.h5
```

Then resubmit the batch that includes that shot.

---

## 5. Useful One-Liners

```bash
qstat -u $USER                    # all your jobs
qdel <JOBID>                      # cancel a specific job
qselect -u $USER | xargs qdel    # cancel ALL your jobs (careful!)

# Check proxy health from login node
curl -s --max-time 5 \
  --proxy "http://$(cat /eagle/fusiondl_aesp/harrisn/fdp/.proxy_addr)" \
  https://osg-htc.org -o /dev/null && echo "proxy OK" || echo "proxy DEAD"
```

---

## Next

[08 - Architecture](08_ARCHITECTURE.md)
