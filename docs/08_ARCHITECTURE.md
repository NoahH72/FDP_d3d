# 08 - Architecture

## Goal

Understand the system architecture, data flow, and key environment variables.

---

## 1. System Overview

The Fusion Data Platform (FDP) on ALCF Polaris has three main components:

### 1.1 FDP pixi environment

Installed at `/eagle/fusiondl_aesp/harrisn/fdp/.pixi/envs/default/`.

Contains Python 3.11 and all required libraries:

- `toksearch_d3d` (from the `ga-fdp` conda channel) -- ships `ptdata`, `toksearch`, the `fdp` CLI, and XRootD plugins
- `numba`
- `h5py`
- Additional scientific Python packages

The key package is `toksearch_d3d`. It provides the data access layer that connects to DIII-D data through the Pelican CDN.

### 1.2 HTTP CONNECT proxy

A lightweight asyncio proxy running on a login node that tunnels HTTPS traffic from compute nodes through the login node's internet connection.

- Zero-thread design to fit within the 128-PID cgroup limit on Polaris login nodes.
- Listens on port 18443 and forwards CONNECT requests to the Pelican CDN at `osg-htc.org:443`.
- The proxy address is written to `/eagle/fusiondl_aesp/harrisn/fdp/.proxy_addr` at startup.

### 1.3 Pipeline scripts

- `FetchRawDataChannelWise.py` -- ECEI data pipeline (Ray-based, multi-worker)
- BES pipeline -- similar structure for BES diagnostic data
- Supporting PBS submission scripts and helper utilities

---

## 2. Data Flow

```
Compute Node (PBS job, Ray workers)
  --> ptdata64 C extension (Fortran PTDATA library)
    --> XRootD + Pelican plugin (libXrdClPelican.so)
      --> HTTP CONNECT proxy (login node, port 18443)
        --> Pelican CDN (osg-htc.org:443, ESnet 100 Gb/s)
          --> DIII-D origin server (General Atomics)
```

On the return path, data flows back through the same chain in reverse.

The **pre-stage optimization** changes this flow: it downloads the full archive file once via `pyxrootd` to local `/tmp`, then extracts individual channels locally using `ptdata64` in local mode. This avoids repeated remote round-trips per channel.

---

## 3. File Layout on Eagle

```
/eagle/fusiondl_aesp/harrisn/
├── fdp/                        FDP pixi environment
│   ├── .pixi/envs/default/    Installed env (Python, fdp CLI, libs)
│   ├── pixi.toml              Dependency spec
│   ├── .proxy_addr            Runtime: proxy hostname:port
│   └── scripts/               Proxy, fetch workarounds
├── ECEI-Data/                  Pipeline source code
├── signal_data/
│   ├── ECEI_Assembled/        Output: assembled ECEI HDF5 files
│   ├── BES_Raw/               Output: raw BES HDF5 files
│   └── d3d_raw_data_hdf5/     Legacy raw data shards
└── shot_lists/                 Shot list files
```

---

## 4. Key Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `CONDA_PREFIX` | `/eagle/fusiondl_aesp/harrisn/fdp/.pixi/envs/default` | Plugin and cert path discovery |
| `PREFIX` | same as above | Fallback if `CONDA_PREFIX` is unset |
| `ALL_PROXY` | `http://polaris-login-XX:18443` | Routes XRootD HTTPS through the proxy |
| `all_proxy` | same as above | Case-insensitive fallback |
| `PTDATA_LOC` | `1` | Remote (Pelican) mode, not local athena |
| `PTDATA_JSON_INDEX_DIR` | `pelican://osg-htc.org:443/fdp-d3d/archives/index/json/...` | Shot index file location |
| `PTDATA_PLUGIN_LIB` | `$CONDA_PREFIX/lib/libjson_index_plugin.so` | JSON index plugin |
| `PTDATA_LIBRARY` | `$CONDA_PREFIX/lib/libd3.so` | PTDATA Fortran library |
| `XRD_PLUGINCONFDIR` | `$CONDA_PREFIX/etc/xrootd/client.plugins.d` | XRootD plugin config dir |
| `X509_CERT_FILE` | `$CONDA_PREFIX/ssl/cacert.pem` | SSL CA bundle |
| `XRDCP_ALLOW_HTTP` | `true` | Allow HTTP in XRootD |
| `XRD_PELICANUSEAUTHHEADERS` | `true` | Send auth headers to Pelican |
| `BEARER_TOKEN` | (from `~/.fdp/token`) | Pelican/OSDF authentication |
| `OPENBLAS_NUM_THREADS` | `1` | Prevent OpenBLAS thread crash |
| `OMP_NUM_THREADS` | `1` | Prevent thread oversubscription |

**NOTE:** `fdp run <cmd>` sets all of these automatically. When using the pixi Python directly (without `fdp run`), you must set `CONDA_PREFIX` and `PREFIX` manually.

---

## 5. Import Compatibility

The FDP pixi environment moved `PtDataSignal` from `toksearch` to `toksearch_d3d`. The pipeline handles this with backward-compatible imports:

```python
import toksearch as ts
if not hasattr(ts, 'PtDataSignal'):
    from toksearch_d3d import PtDataSignal
    ts.PtDataSignal = PtDataSignal
```

`MdsSignal` remains in `toksearch` and does not require any compatibility shim.

---

## Next

[09 - Performance](09_PERFORMANCE.md)
