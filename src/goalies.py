"""Goalie data: who started each game (NHL stats API) and each goalie's
game-by-game goals vs expected goals faced (MoneyPuck)."""
import io
import json
import os
import time
import urllib.error
import urllib.request

import pandas as pd
import paths

STARTS = paths.data("goalie_starts.csv")
GOALIE_GAMES = paths.data("goalie_games.csv")
MP_GOALIE = "https://moneypuck.com/moneypuck/playerData/careers/gameByGame/regular/goalies/{}.csv"
NHL_LOG = ("https://api.nhle.com/stats/rest/en/goalie/summary?isAggregate=false&isGame=true&limit=-1"
           "&cayenneExp=seasonId={}%20and%20gameTypeId=2")


def get(url, tries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as f:
                return f.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(30 * (i + 1))  # rate limited: back off


def refresh(seasons):
    """Re-download starts for `seasons`, then MoneyPuck files only for goalies
    who have played a game we don't have yet."""
    old = pd.read_csv(STARTS) if os.path.exists(STARTS) else pd.DataFrame()
    rows = []
    for s in seasons:
        data = json.loads(get(NHL_LOG.format(f"{s}{s + 1}")))["data"]
        rows += [{"season": s, "gameId": d["gameId"], "team": d["teamAbbrev"], "playerId": d["playerId"],
                  "name": d["goalieFullName"], "started": d["gamesStarted"]} for d in data]
    new = pd.DataFrame(rows)
    if len(old):
        new = pd.concat([old[~old.season.isin(seasons)], new])
    new.to_csv(STARTS, index=False)

    have = pd.read_csv(GOALIE_GAMES) if os.path.exists(GOALIE_GAMES) else pd.DataFrame(columns=["playerId"])
    known = set(zip(have.playerId, have.gameId)) if len(have) else set()
    cur = new[new.season.isin(seasons)]  # only chase games from the seasons being refreshed
    need = {p for p, g in zip(cur.playerId, cur.gameId) if (p, g) not in known}
    parts = [have[~have.playerId.isin(need)]]
    for i, pid in enumerate(sorted(need)):
        time.sleep(1.5)  # be polite to MoneyPuck
        print(f"  goalie {i + 1}/{len(need)}", end="\r")
        try:
            d = pd.read_csv(io.BytesIO(get(MP_GOALIE.format(pid))))
            d = d[d.situation == "all"]
            parts.append(d[["playerId", "season", "gameId", "gameDate", "name", "xGoals", "goals"]])
        except Exception as e:
            print(f"  skip goalie {pid}: {e} (keeping their saved history)")
            parts.append(have[have.playerId == pid])  # a failed download must never erase what we had
    if need:
        print()
    pd.concat(parts).to_csv(GOALIE_GAMES, index=False)
