"""Fill in data/key_players/<day>.json for past days that have no pre-game snapshot (before Oct 13 2026), from who
actually dressed (NHL box scores). Same ranking and effect as injuries.key_players, with the team's games and each
player's games for that team counted as of the game day; player ratings are today's (small hindsight). Status:
'in' = dressed, 'out' = didn't. Marked rebuilt=True so the dashboard says so. Never overwrites a day that has a file.

  python3 research/lib/backfill_key_players.py 2026-10-01 2026-10-12
"""
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
import pandas as pd

import injuries
import lineups
import model as m
import paths
import players

BOX = "https://api-web.nhle.com/v1/gamecenter/{}/boxscore"
SCHED = "https://api-web.nhle.com/v1/club-schedule-season/{}/{}{}"


def get(url):
    with urllib.request.urlopen(m.fetch(url), timeout=30) as f:
        return json.load(f)


def main(first, last, season=2026, top=5):
    log = pd.read_csv(paths.data("paper_trades.csv"))
    days = sorted(d for d in log.date.unique() if first <= d <= last)
    teams = sorted(set(log.away) | set(log.home))
    games = {}  # gameId -> (date, {team: set(dressed ids)})
    for t in teams:
        for g in get(SCHED.format(t, season, season + 1))["games"]:
            if g["gameType"] == 2 and g["gameState"] in ("OFF", "FINAL") and g["gameDate"] <= last and g["id"] not in games:
                b = get(BOX.format(g["id"]))
                games[g["id"]] = (g["gameDate"], {b[s]["abbrev"]: {p["playerId"] for p in b["playerByGameStats"][s]["forwards"]
                                                                   + b["playerByGameStats"][s]["defense"]}
                                                  for s in ("homeTeam", "awayTeam")})
                time.sleep(0.2)
    pt = players.player_table(season).set_index("playerId")
    rosters = {t: {p for p, _, _ in lineups.nhl_roster(t)} for t in teams}
    known = defaultdict(set)  # today's key players (catches regulars hurt since opening night, e.g. on IR)
    for f in os.listdir(paths.data("key_players")):
        for t, v in json.load(open(paths.data(f"key_players/{f}")))["teams"].items():
            known[t] |= {p["name"] for side in ("off", "def") for p in v[side]}
    by_name = pt.reset_index().set_index("name")
    for day in days:
        path = paths.data(f"key_players/{day}.json")
        if os.path.exists(path):
            print(f"{day}: has a file, skipped")
            continue
        before = [(d, x) for d, x in games.values() if d < day]
        tonight = {t: ids for d, x in games.values() if d == day for t, ids in x.items()}
        out = {}
        for t, dressed in tonight.items():
            n = sum(t in x for _, x in before)
            gp = defaultdict(int)
            for _, x in before:
                for p in x.get(t, ()):
                    gp[p] += 1
            season_ids = {p for _, x in before + [(day, tonight)] for p in x.get(t, ())}
            last_regulars = {p for p in pt.index[pt.team_last == t] if p in rosters[t]}
            named = {int(by_name.loc[nm, "playerId"]) for nm in known[t] if nm in by_name.index and not isinstance(by_name.loc[nm, "playerId"], pd.Series)}
            rows = []
            for pid in (season_ids | last_regulars | named) & set(pt.index):
                p = pt.loc[pid].copy()
                p["gp_cur"], p["team_cur"] = gp[pid], (t if pid in season_ids else None)
                eff = injuries._effect(p, t, n)
                rows.append((p, pid in dressed, eff))
            out[t] = {side: [{"name": p["name"], "pos": p.position, "impact": round(injuries.SCALE * eff[k], 4),
                              "status": "in" if played else "out", "tag": ""}
                             for p, played, eff in sorted(rows, key=lambda x: -x[2][k])[:top]]
                      for k, side in ((0, "off"), (1, "def"))}
        with open(path, "w") as f:
            json.dump({"date": day, "rebuilt": True, "teams": out}, f, separators=(",", ":"))
        print(f"{day}: {len(out)} teams")


if __name__ == "__main__":
    main(*sys.argv[1:3])
