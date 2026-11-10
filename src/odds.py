"""Historical NHL totals from Action Network: book 15 = consensus close, book 30 = opening line."""
import json
import os
import time
import urllib.request
from datetime import date, timedelta

import pandas as pd
import paths

ODDS = paths.data("odds_history.csv")
ODDS_OPEN = paths.data("odds_open.csv")
URL = "https://api.actionnetwork.com/web/v2/scoreboard/nhl?period=game&date={}"  # v2 since Nov 10 2026 (v1 answers 404)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SEASONS = [(date(2022, 10, 1), date(2023, 4, 20)), (date(2023, 10, 1), date(2024, 4, 25)),
           (date(2024, 10, 1), date(2025, 4, 25)), (date(2025, 10, 1), date(2026, 4, 25))]


def scoreboard(d):
    """Action Network's NHL scoreboard for one day (v2)."""
    req = urllib.request.Request(URL.format(d.strftime("%Y%m%d")), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as f:
        return json.load(f)


def totals(g):
    """{book id: (total, over price, under price)} for one v2 game: each book's main game total (markets -> book ->
    event -> total: an over and an under at the same value; live and alternate lines skipped)."""
    out = {}
    for book, mk in (g.get("markets") or {}).items():
        ts = [o for o in ((mk or {}).get("event") or {}).get("total") or []
              if not o.get("is_live") and not o.get("is_alt_market") and o.get("odds") is not None and o.get("value") is not None]
        under = {o["value"]: o["odds"] for o in ts if o.get("side") == "under"}
        for o in ts:
            if o.get("side") == "over" and o["value"] in under:
                out[int(book)] = (float(o["value"]), int(o["odds"]), int(under[o["value"]]))
                break
    return out


def day_games(d, book=15, completed_only=True, data=None):
    """One row per game with book's total (15 = consensus, 30 = opening line). data: an already-read scoreboard."""
    data = scoreboard(d) if data is None else data
    rows = []
    for g in data.get("games", []):
        if completed_only and g.get("status") != "complete":
            continue
        line = totals(g).get(book)
        if not line:
            continue
        teams = {t["id"]: t["abbr"] for t in g["teams"]}
        rows.append({"date": d.isoformat(), "start": g["start_time"], "home": teams[g["home_team_id"]],
                     "away": teams[g["away_team_id"]], "total": line[0], "over": line[1], "under": line[2]})
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
