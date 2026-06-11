# 03 - Proxy Setup

## Goal

Set up the HTTPS proxy that lets Polaris compute nodes access the internet through a login node, enabling FDP data fetches.

---

## Prerequisites

Complete [02 - Installation](02_INSTALLATION.md) before continuing.

---

## Background

FDP fetches DIII-D data from Pelican/OSDF endpoints at `osg-htc.org:443` via HTTPS. However:

- Polaris **compute nodes** have **no outbound internet access**.
- Polaris **login nodes** do have internet access.

The solution is a lightweight HTTP CONNECT proxy (`scripts/https_proxy.py`) that runs on a login node and routes all HTTPS traffic from compute nodes through the login node's internet connection.

Key details about the proxy:

- It is asyncio-based and zero-thread, staying within the login node's 128-PID cgroup limit.
- It uses only Python stdlib (no extra dependencies).
- It writes its hostname and port to a `.proxy_addr` file so PBS jobs can discover it automatically, regardless of which login node you are on.
- XRootD's curl plugin respects `ALL_PROXY` (uppercase) but **not** `https_proxy` (lowercase) alone. Both environment variables must be set for data fetches to work. The PBS scripts in this repo handle this automatically.

---

## Steps

### 1. Set up SSH keys (one-time)

Compute nodes need passwordless SSH access back to login nodes (for tunnel setup in some configurations). Ensure your public key is in `authorized_keys`:

```bash
ls ~/.ssh/authorized_keys
```

If the file is missing or does not contain your key:

```bash
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

If you do not have an SSH key pair, generate one first with `ssh-keygen -t ed25519`.

### 2. Start the proxy in a detached screen session

From a Polaris **login node**, run:

```bash
screen -dmS fdp_proxy python3 $PROJECT_ROOT/scripts/https_proxy.py --port 18443
```

Replace `$PROJECT_ROOT` with the path to your clone of this repository (e.g., `/eagle/fusiondl_aesp/harrisn/FDP_d3d`).

The proxy starts in the background inside a `screen` session named `fdp_proxy`.

### 3. Verify it started

```bash
screen -ls                    # should show "fdp_proxy"
sleep 2
cat /eagle/fusiondl_aesp/harrisn/fdp/.proxy_addr   # shows hostname:port
```

You should see a line like `polaris-login-01:18443` (the exact hostname depends on which login node you are on).

### 4. Test connectivity

```bash
https_proxy=http://localhost:18443 curl -s -o /dev/null -w "%{http_code}" https://osg-htc.org
```

Expected output:

```
200
```

If you get a connection error, check that the screen session is still running (`screen -ls`) and that port 18443 is not in use by another process.

---

## Important Notes

- **Survives SSH disconnects:** The proxy runs inside `screen`, so it persists if your SSH session drops or you disconnect from Cursor.
- **Does NOT survive login node reboots:** If you start getting connection errors from compute nodes, the login node may have rebooted. Restart the proxy (step 2).
- **Port selection:** Port 18443 avoids conflicts with standard ports. Change it via the `--port` flag if needed.
- **Watch proxy logs:** `screen -r fdp_proxy` (detach with `Ctrl+A D`).
- **Stop the proxy:** `screen -S fdp_proxy -X quit`
- **Check if proxy is running:** `screen -ls | grep fdp_proxy`

---

## Verify

Confirm that the curl test in step 4 returns `200`. This means the proxy is running and can reach the Pelican/OSDF endpoints that FDP uses.

---

## Next

Continue to [04 - Running ECEI Pipeline](04_RUNNING_ECEI_PIPELINE.md).
