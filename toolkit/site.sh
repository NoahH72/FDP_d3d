# Sourced by every toolkit shell script. Loads sites/site.env and defines helpers. Never prints the token.
#   FDP_SITE_ENV  path of the site file (default: <repo>/sites/site.env)
#   FDP_ENV_KIND  new (default) | old   which FDP environment to launch
TOOLKIT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(dirname "$TOOLKIT_DIR")
FDP_SITE_ENV=${FDP_SITE_ENV:-$REPO_DIR/sites/site.env}
[ -f "$FDP_SITE_ENV" ] || { echo "missing $FDP_SITE_ENV: copy sites/<site>.env.example to sites/site.env and fill it in"; return 2 2>/dev/null || exit 2; }
# shellcheck disable=SC1090
. "$FDP_SITE_ENV"
grep -q "<YOUR_" "$FDP_SITE_ENV" && { echo "$FDP_SITE_ENV still has <YOUR_...> placeholders"; return 2 2>/dev/null || exit 2; }
FDP_ENV_KIND=${FDP_ENV_KIND:-new}

fdp_proxy() {  # compute nodes reach the internet only through the site proxy
  export http_proxy=$PROXY https_proxy=$PROXY HTTP_PROXY=$PROXY HTTPS_PROXY=$PROXY ALL_PROXY=$PROXY all_proxy=$PROXY
}

fdp_env() {  # environment for a fetch: single-threaded numerics, no interactive login, no exported token
  unset BEARER_TOKEN
  export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 FDP_NO_AUTO_LOGIN=1 XRD_CURLDISABLEPREFETCH=1
  export FDP_INDEX_SNAPSHOT
  if [ "$FDP_ENV_KIND" = old ]; then
    export CONDA_PREFIX=$FDP_OLD_ENV PREFIX=$FDP_OLD_ENV LD_LIBRARY_PATH=$FDP_OLD_ENV/lib:${LD_LIBRARY_PATH:-}
    FDP_BIN=$FDP_OLD_ENV/bin
  else
    FDP_BIN=$FDP_NEW_ENV/bin
  fi
  export PATH=$FDP_BIN:$PATH
}

fdp_launch() {  # fdp_launch script.py args...   (runs under `fdp run`, which supplies the token and tree paths)
  if [ "$FDP_ENV_KIND" = old ]; then "$FDP_BIN/fdp" run "$FDP_BIN/python" "$@"
  else "$FDP_BIN/fdp" run --device d3d "$FDP_BIN/python" "$@"; fi
}

fdp_token_ok() {  # fdp_token_ok HOURS  -> exit status 0 if the token has read scope and HOURS left
  python3 "$TOOLKIT_DIR/token_status.py" "$1"
}

fdp_proxy_ok() {  # one retry after 60 s; outages of a few minutes happen
  curl -s --max-time 20 https://osg-htc.org -o /dev/null && return 0
  sleep 60; curl -s --max-time 20 https://osg-htc.org -o /dev/null
}

wall_seconds() { echo "$1" | awk -F: '{print $1*3600+$2*60+$3}'; }
