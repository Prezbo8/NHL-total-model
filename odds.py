"""Historical NHL totals from Action Network: book 15 = consensus close, book 30 = opening line."""
import json
import os
import time
import urllib.request
from datetime import date, timedelta

import pandas as pd

ODDS = "odds_history.csv"
ODDS_OPEN = "odds_open.csv"
URL = "https://api.actionnetwork.com/web/v1/scoreboard/nhl?period=game&date={}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SEASONS = [(date(2022, 10, 1), date(2023, 4, 20)), (date(2023, 10, 1), date(2024, 4, 25)),
           (date(2024, 10, 1), date(2025, 4, 25)), (date(2025, 10, 1), date(2026, 4, 25))]


def day_games(d, book=15, completed_only=True):
    req = urllib.request.Request(URL.format(d.strftime("%Y%m%d")), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as f:
        data = json.load(f)
    rows = []
    for g in data.get("games", []):
        teams = {t["id"]: t["abbr"] for t in g["teams"]}
        cons = [o for o in g.get("odds", []) if o.get("book_id") == book and o.get("total") is not None]
        if (completed_only and g.get("status") != "complete") or not cons:
            continue
        o = cons[0]
        rows.append({"date": d.isoformat(), "start": g["start_time"], "home": teams[g["home_team_id"]],
                     "away": teams[g["away_team_id"]], "total": o["total"], "over": o["over"], "under": o["under"]})
    return rows


def fetch_all(book=15, path=ODDS):
    done = set(pd.read_csv(path).date) if os.path.exists(path) else set()
    rows = []
    for start, end in SEASONS:
        d = start
        while d <= end:
            if d.isoformat() not in done:
                try:
                    rows += day_games(d, book)
                except Exception as e:
                    print(d, "error", e)
                time.sleep(1)
            d += timedelta(days=1)
        if rows:
            old = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()
            pd.concat([old, pd.DataFrame(rows)]).to_csv(path, index=False)
            rows = []
        print("done season starting", start, flush=True)


if __name__ == "__main__":
    import sys
    fetch_all(30, ODDS_OPEN) if "open" in sys.argv else fetch_all()
