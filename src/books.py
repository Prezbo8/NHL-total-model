"""All sportsbooks' NHL totals per game from Action Network (for line shopping)."""
import json
import os
import time
import urllib.request
from datetime import timedelta

import pandas as pd

import odds
import paths

BOOKS = paths.data("odds_books.csv")


NOT_BOOKS = {15, 30}  # Action Network's consensus and opening lines, not bettable
MINE = ("DK", "DraftKings", "FanDuel", "BetRivers", "BetMGM", "Caesars")  # the books the owner bets (Nov 9 2026)


def mine(name):
    """True for one of MINE ('DK NJ', 'BetMGM NJ', ...): 'Best over' only considers these."""
    return str(name).split(" ")[0] in MINE


def book_names():
    req = urllib.request.Request("https://api.actionnetwork.com/web/v1/books", headers={"User-Agent": odds.UA})
    with urllib.request.urlopen(req, timeout=30) as f:
        return {b["id"]: b["display_name"] for b in json.load(f)["books"]}


def day_all_books(d, completed_only=True, data=None):
    """Every book's total for each game (Action Network v2 scoreboard, odds.totals). data: an already-read scoreboard."""
    data = odds.scoreboard(d) if data is None else data
    rows = []
    for g in data.get("games", []):
        if completed_only and g.get("status") != "complete":
            continue
        teams = {t["id"]: t["abbr"] for t in g["teams"]}
        for book, (total, over, under) in odds.totals(g).items():
            rows.append({"date": d.isoformat(), "home": teams[g["home_team_id"]], "away": teams[g["away_team_id"]],
                         "book": book, "total": total, "over": over, "under": under})
    return rows


def fetch_all():
    done = set(pd.read_csv(BOOKS).date) if os.path.exists(BOOKS) else set()
    for start, end in odds.SEASONS[1:]:  # 2022-23 only has the consensus line
        rows, d = [], start
        while d <= end:
            if d.isoformat() not in done:
                for attempt in range(3):
                    try:
                        rows += day_all_books(d)
                        break
                    except Exception as e:
                        print(d, "error", e, flush=True)
                        time.sleep(10)
                time.sleep(1)
            d += timedelta(days=1)
        old = pd.read_csv(BOOKS) if os.path.exists(BOOKS) else pd.DataFrame()
        pd.concat([old, pd.DataFrame(rows)]).to_csv(BOOKS, index=False)
        print("done season starting", start, flush=True)


if __name__ == "__main__":
    fetch_all()
