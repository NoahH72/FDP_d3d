# 02 Tokens

## How it works

- `fdp login --device d3d` runs the `pelican` client, which does a GitHub device login against the DIII-D issuer
  (`fdp-d3d-origin.nationalresearchplatform.org:8000`) and writes a JWT to `~/.fdp/cache/d3d.token`.
- A good token has `scope` containing `storage.read:/` and `wlcg.groups: ['DIII-D']`.
- **Tokens last 24 hours.** Pelican keeps a refresh token, so `fdp login` renews silently for about 30 days before it
  needs a browser approval again.
- `fdp login` returns the **current** token until it expires, however little time is left. Only
  `fdp login --fresh --device d3d` gets a new full 24 h token (one browser approval).
- **A job keeps the token it started with.** Nothing renews it inside a running job. `fdp run` reads it at launch.
- Each machine has its own home directory, so Polaris and Aurora each need their own login and their own daily refresh.

## Rules

- Only the account owner logs in (the device flow needs a browser approval). Agents and jobs never run an interactive login.
- **Never print, copy, log or export the token.** Never `export BEARER_TOKEN`; a stale exported value causes confusing
  401s. `unset BEARER_TOKEN` in every job (the toolkit does).
- Check the token before submitting and at job start. The toolkit's `run_slice.pbs` exits 3 if the token will not
  outlast the walltime (+15 min); `chain_driver.sh` stops submitting when it has less than walltime + 0.3 h left.

## Check (safe for anyone; never logs in)

```bash
python3 toolkit/token_status.py        # scope, expiry, hours left
python3 toolkit/token_status.py 12     # exit 1 if less than 12 h left
```

## Refresh (account owner, in a real terminal on a login node)

```bash
cd $WORK_ROOT/fdp-2026-11 && unset BEARER_TOKEN && PATH=$PWD/.pixi/envs/default/bin:$PATH fdp login --fresh --device d3d
```
Approve the URL in a browser. It can take a minute or two to complete. Then `python3 toolkit/token_status.py`.

## Planning a campaign around expiry

- Hours needed = wait until the job **starts** + walltime + margin. With 1 h jobs the driver keeps submitting until the
  token has about 1.3 h left, then stops; queued jobs that start later refuse to run (exit 3, "token too short").
- Daily rhythm that worked for multi-day campaigns: the owner runs `fdp login --fresh` once a day; the agent restarts
  the driver afterwards. Slices refused by an expiring token are not lost: their shots have no status file and are
  picked up again (reset the driver's `state/NEXT` to the first refused slice, or let the retry pass take them).

## If the token is expired (agents)

1. `token_status.py`. If it says **expired**, one silent renewal attempt is allowed:
   `cd $WORK_ROOT/fdp-2026-11 && unset BEARER_TOKEN && PATH=$PWD/.pixi/envs/default/bin:$PATH timeout 120 fdp login --device d3d`.
   Success prints `Logged in to d3d (read); token valid until ...`.
2. If it prints an approval URL, asks for a password, times out, or the token is valid but too short: stop and ask the
   owner to run the refresh command above.

## Gotchas

- **Stale browser cookie.** The issuer reads your GitHub orgs from a 16 h browser cookie set when you first signed in.
  If org membership changed since, the token lacks `storage.read` and pelican fails with
  `Error code 4000: acquired token not valid for /fdp-d3d`. Approve in a **private window**, or log out at
  https://fdp-d3d-origin.nationalresearchplatform.org:8000/.
- **Pelican password prompt.** If pelican asks to create a password for its local credential store, press Enter (empty)
  so renewals never prompt. To reset: `.pixi/envs/default/bin/pelican credentials reset-local`, then `fdp login`.
  Pelican's prompt can echo the password in plain text; `clear` the terminal afterwards.
