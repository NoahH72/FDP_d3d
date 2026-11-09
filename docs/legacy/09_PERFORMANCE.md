# 09 - Performance

## Goal

Understand pipeline performance, benchmarks, and scaling.

---

## 1. Performance Summary

| Configuration | Per-shot | 9890 shots | Notes |
|---------------|----------|------------|-------|
| 1 node, 8 workers (no pre-stage) | 137 s | ~377 hr | Sequential remote fetch |
| 1 node, 8 workers (pre-stage) | 21.1 s | ~58 hr | Parallel pre-stage |
| 1 node, 16 workers (pre-stage) | 18.6 s | ~51 hr | Best single-node |
| 10 nodes, 16 workers each | ~18.6 s | ~5 hr | Production target |

---

## 2. The Bottleneck

The **network is NOT the bottleneck**. Raw XRootD copy achieves 93.2 MB/s (745 Mbps) through the proxy.

The bottleneck is `ptdata64` per-channel extraction: approximately 5 seconds per channel call regardless of whether the data is local or remote. The archive scanning, binary decoding, and array allocation in the Fortran PTDATA library dominate the processing time.

---

## 3. Pre-Stage Optimization (the 6.5x speedup)

The pre-stage optimization reduces per-shot time from ~137 s to ~21 s. It works as follows:

1. **Before each pass:** Download all archive files for shots in the batch to local `/tmp` via `pyxrootd`.
2. **Replace `pipe.fetch()`** with a custom `pipe.map()` that uses `concurrent.futures.ThreadPoolExecutor` to read all 40 channels from the local archive in parallel.
3. **Thread layout:** 8 threads per worker, each extracting 5 channels. `ptdata64` releases the GIL for I/O, so true parallelism is achieved.
4. **Cross-pass caching:** Pass 0 downloads the archive files. Passes 1-3 find the data already in `/tmp` and skip the download step entirely.

---

## 4. Polaris vs Saga

| Factor | Saga (GA) | Polaris (ALCF) |
|--------|-----------|----------------|
| Data location | Local GPFS/BeeGFS | Remote Pelican CDN |
| Per-shot time | ~10 s | 21 s (optimized) |
| Network overhead | 0 | ~20 s download (amortized) |
| ptdata64 per-channel | ~5 s (local) | ~5 s (local after pre-stage) |

The ~2x gap between Saga and Polaris is entirely from the one-time download cost per shot (~1.2 GB from CDN).

---

## 5. Data Sizes

| Quantity | Value |
|----------|-------|
| ECEI channels per shot | 160 (20 rows x 8 cols) |
| PTDATA archive per shot | ~1.2 GB |
| ECEI output HDF5 per shot | ~few hundred MB (lzf compressed) |
| BES channels per shot | 64 |
| BES output HDF5 per shot | ~150 MB (gzip-4) |
| Full dataset (9890 shots ECEI) | ~several TB |

---

## 6. Scaling Projections

| Nodes | Workers/node | Est. wall time (9890 shots) |
|-------|-------------|---------------------------|
| 1 | 16 | ~51 hr |
| 4 | 16 | ~13 hr |
| 10 | 16 | ~5 hr |
| 20 | 16 | ~2.5 hr |

---

## 7. Tuning

- **`RAY_MAX_WORKERS`**: Default 16. Increasing beyond 16 may help throughput but memory may become the limiting factor.
- **`ROWS_PER_PASS`**: Default 5 (4 passes for 20 ECEI rows). Higher values mean fewer passes but more memory per worker.
- **Pre-stage (`ECEI_PRESTAGE=1`)**: Always recommended. Disabling falls back to sequential remote fetch and ~6.5x slower per-shot times.
- **Workers beyond 16**: Polaris nodes have 64 CPU cores. Consider testing 24-32 workers/node, but monitor memory usage first.

---

## Previous

[08 - Architecture](08_ARCHITECTURE.md)
