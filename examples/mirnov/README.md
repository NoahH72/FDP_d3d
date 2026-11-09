# Example: the Mirnov campaign (Polaris, 2026-10/11)

The complete code of a production fetch campaign: DIII-D magnetic probes from PTDATA through FDP, old env (ptdata
1.4.6, bit-identical to GA's saga references), about 9 TB over three jobs. It predates `toolkit/` and is kept as a
worked example; paths are placeholders (`/eagle/<YOUR_PROJECT>/<YOUR_USERNAME>/mirnov_2026-10`).

| File | Role |
|---|---|
| `mirnov_fetch.py`, `mirnov_fetch_t2.py`, `mirnov_fetch_t3.py` | per-shot fetchers for job 1 (`MPI66M###D`), job 2 (other `MPI*D`), job 3 (`B1`-`B8`): index-based absent/error, float32 only with the per-channel lossless check (raw counts re-fetched on `shot % 20 == 0`), time bases stored once, atomic writes, status JSON |
| `probe_api.py`, `probe_identity.py` | API probe of the new env and bit-identity checks against saga reference values |
| `smoke_t2.pbs`, `smoke_t3.pbs`, `smoke_report_t3.py` | smoke tests (smoke shots + negative controls + lane scaling) and the report |
| `common.py`, `ledger.py`, `promote.py` | ledger CSV, slice cutting, staging -> store promotion with MANIFEST |
| `run_slice_t2.pbs`, `chain_driver_t2.sh` | one slice per job; login-node driver feeding two queues, lock + heartbeat, background promote |
| `cap_worker_t2.sh`, `run_cap_t2.pbs` | multi-node capacity job whose workers claim slices from the top of the series |
| `recut_slices_t2.py` | re-cut unsubmitted slices (same shots, same order) after a lane change |
| `final_report.py`, `write_readme_t2.py` | final report and store README (provenance, identity, counts, open items) |

Lessons from it are folded into docs/04-06 and the toolkit.
