"""All sportsbooks' NHL totals per game from Action Network (for line shopping)."""
import json
import os
import time
import urllib.request
from datetime import timedelta

import pandas as pd

import odds

BOOKS = "odds_books.csv"


NOT_BOOKS = {15, 30}  # Action Network's consensus and opening lines, not bettable


def book_names():
    req = urllib.request.Request("https://api.actionnetwork.com/web/v1/books", headers={"User-Agent": odds.UA})
    with urllib.request.urlopen(req, timeout=30) as f:
        return {b["id"]: b["display_name"] for b in json.load(f)["books"]}


def day_all_books(d, completed_only=True):
    req = urllib.request.Request(odds.URL.format(d.strftime("%Y%m%d")), headers={"User-Agent": odds.UA})
    with urllib.request.urlopen(req, timeout=30) as f:
        data = json.load(f)
    rows = []
    for g in data.get("games", []):
        if completed_only and g.get("status") != "complete":
            continue
        teams = {t["id"]: t["abbr"] for t in g["teams"]}
        for o in g.get("odds", []):
            if o.get("total") is None or o.get("over") is None or o.get("under") is None:
                continue
            rows.append({"date": d.isoformat(), "home": teams[g["home_team_id"]], "away": teams[g["away_team_id"]],
                         "book": o["book_id"], "total": o["total"], "over": o["over"], "under": o["under"]})
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
