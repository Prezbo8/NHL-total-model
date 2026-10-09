"""Who dressed in every regular-season game since 2020-21 (NHL box scores), for backtesting the injury /
lineup adjustment.

  python3 research/lib/lineups_hist.py download    # -> data/dressed.csv (resumable; gitignored, ~10 MB)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
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

OUT = paths.data("dressed.csv")
COLS = ["gameId", "team", "playerId", "name", "pos", "toi"]


def toi(s):
    mm, ss = (s or "0:0").split(":")
    return int(mm) * 60 + int(ss)


def one(gid):
    for i in range(4):
        try:
            with urllib.request.urlopen(m.fetch(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore"), timeout=20) as f:
                b = json.load(f)
            rows = []
            for k in ("awayTeam", "homeTeam"):
                team = b[k]["abbrev"]
                for grp in ("forwards", "defense", "goalies"):
                    for p in b.get("playerByGameStats", {}).get(k, {}).get(grp, []):
                        rows.append({"gameId": gid, "team": team, "playerId": p.get("playerId"),
                                     "name": (p.get("name") or {}).get("default", ""), "pos": p.get("position"),
                                     "toi": toi(p.get("toi"))})
            return rows
        except Exception:
            time.sleep(2 * (i + 1))
    return []


def download():
    ids = sorted(set(sm.load_split().gameId.astype(int)))
    have = pd.read_csv(OUT) if os.path.exists(OUT) else pd.DataFrame(columns=COLS)
    todo = [g for g in ids if g not in set(have.gameId)]
    print(f"{len(ids)} games, {len(todo)} to download", flush=True)
    rows, done = [], 0
    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(one, todo):
            rows += r; done += 1
            if done % 500 == 0 or done == len(todo):
                have = pd.concat([have, pd.DataFrame(rows, columns=COLS)], ignore_index=True); rows = []
                have.to_csv(OUT, index=False); print(f"  {done}/{len(todo)}", flush=True)
            time.sleep(0.05)


if __name__ == "__main__":
    download() if sys.argv[1:] == ["download"] else print(__doc__)
