# 03 Network

Compute nodes have no direct internet access. **Use the ALCF proxy.** It carries everything FDP needs: PTDATA
archives, MDSplus, the PTDATA json index, token checks (verified on Polaris 2026-10-13, and it carried the ECEI/BES/
Mirnov campaigns: up to 2 nodes x 64 lanes in parallel, several TB).

```bash
export http_proxy=http://proxy.alcf.anl.gov:3128 https_proxy=http://proxy.alcf.anl.gov:3128
export HTTP_PROXY=$http_proxy HTTPS_PROXY=$https_proxy ALL_PROXY=$https_proxy all_proxy=$https_proxy
```

- XRootD honours `ALL_PROXY`/`all_proxy`, **not** `https_proxy` alone: set all of them (`fdp_proxy` in `toolkit/site.sh`).
- `XRD_CURLDISABLEPREFETCH=1` is set for every fetch (it was in the configuration that produced the stores).
- Login nodes have direct access; one-shot probes there need no proxy.
- Reachability check used at job start: `curl -s --max-time 20 https://osg-htc.org -o /dev/null`, retried once after
  60 s (short outages happen). The toolkit stops the job (exit 5) if both fail.

## Superseded: the login-node proxy

Until 2026-10 the ECEI/BES pipelines used `scripts/https_proxy.py` in a `screen` session on a login node, with its
address in `fdp/.proxy_addr`. That is no longer needed (and the login-node session died whenever the node rebooted).
The old pipelines still read `.proxy_addr`: put `proxy.alcf.anl.gov:3128` in it.

## Aurora

ALCF documents the same proxy for Aurora compute nodes; **not yet verified for FDP** there. The selftest
(`toolkit/selftest.pbs`) checks it; see docs/07.
