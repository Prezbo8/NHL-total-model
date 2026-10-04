"""Referee assignments for every regular-season game since 2020-21 (NHL gamecenter right-rail).

  python3 research/refs.py download     # -> data/referees.csv (resumable)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import model as m
import paths
import split_model as sm

OUT = paths.data("referees.csv")


def one(gid):
    for i in range(4):
        try:
            with urllib.request.urlopen(m.fetch(f"https://api-web.nhle.com/v1/gamecenter/{gid}/right-rail"), timeout=20) as f:
                gi = json.load(f).get("gameInfo") or {}
            refs = sorted(r["fullName"]["default"] for r in gi.get("referees", []))
            return {"gameId": gid, "ref1": refs[0] if refs else None, "ref2": refs[1] if len(refs) > 1 else None}
        except Exception:
            time.sleep(2 * (i + 1))
    return {"gameId": gid, "ref1": None, "ref2": None}


def download():
    games = sm.load_split()
    ids = sorted(set(games.gameId.astype(int)))
    have = pd.read_csv(OUT) if os.path.exists(OUT) else pd.DataFrame(columns=["gameId", "ref1", "ref2"])
    todo = [g for g in ids if g not in set(have.gameId)]
    print(f"{len(ids)} games, {len(todo)} to download", flush=True)
    rows = []
    with ThreadPoolExecutor(4) as ex:
        for i, r in enumerate(ex.map(one, todo), 1):
            rows.append(r)
            if i % 500 == 0 or i == len(todo):
                have = pd.concat([have, pd.DataFrame(rows)], ignore_index=True); rows = []
                have.to_csv(OUT, index=False); print(f"  {i}/{len(todo)}", flush=True)
            time.sleep(0.05)


if __name__ == "__main__":
    download() if sys.argv[1:] == ["download"] else print(__doc__)
