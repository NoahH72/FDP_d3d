"""Report how long the FDP d3d bearer token has left, without ever logging in.

    python3 toolkit/token_status.py [MIN_HOURS]

Reads ~/.fdp/cache/d3d.token (written by `fdp login`; ~/.fdp/token is a symlink
to it for the old env). Exits 0 if the token has read scope and at least
MIN_HOURS left (default 0), else 1. Never prints the token itself.
"""
import base64
import json
import os
import sys
import time

PATH = os.path.expanduser("~/.fdp/cache/d3d.token")
min_hours = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0

try:
    tok = open(PATH).read().strip()
    p = tok.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
except (OSError, IndexError, ValueError) as exc:
    print(f"NO TOKEN: cannot read {PATH} ({exc}). A human must run `fdp login --device d3d` (docs/02_TOKENS.md).")
    sys.exit(1)

left_h = (claims.get("exp", 0) - time.time()) / 3600
scope = claims.get("scope", "")
expires = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(claims.get("exp", 0)))
print(f"sub={claims.get('sub')} groups={claims.get('wlcg.groups')} scope={scope!r}")
print(f"expires {expires}  ({left_h:.1f} h left)")

if "storage.read" not in scope:
    print("BAD: token has no storage.read scope; see docs/02_TOKENS.md (stale browser cookie).")
    sys.exit(1)
if left_h < min_hours:
    print(f"TOO SHORT: need {min_hours:g} h. A human must run `fdp login --fresh --device d3d` (docs/02_TOKENS.md).")
    sys.exit(1)
print("OK")
