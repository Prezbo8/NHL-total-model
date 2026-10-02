"""Older NHL totals (2007-08 to 2022-23) from SportsBookReviewsOnline archives.

Each game is two rows (visitor, home). OpenOU/CloseOU hold the total and a price:
the visitor row's price is the OVER, the home row's is the UNDER.
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))  # model code lives in src/
import re
import time
import urllib.request

import pandas as pd
import paths  # noqa: E402

SBR = paths.data("sbr_odds.csv")
URL = "https://www.sportsbookreviewsonline.com/scoresoddsarchives/nhl-odds-{}/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
# page slug -> season start year (2020-21 is just "2021" on the site)
PAGES = {f"{y}-{str(y + 1)[2:]}": y for y in range(2007, 2023) if y != 2020}
PAGES["2021"] = 2020

TEAMS = {
    "Anaheim": "ANA", "Arizona": "ARI", "Phoenix": "ARI", "Boston": "BOS", "Buffalo": "BUF", "Calgary": "CGY",
    "Carolina": "CAR", "Chicago": "CHI", "Colorado": "COL", "Columbus": "CBJ", "Dallas": "DAL", "Detroit": "DET",
    "Edmonton": "EDM", "Florida": "FLA", "LosAngeles": "LAK", "Minnesota": "MIN", "Montreal": "MTL",
    "Nashville": "NSH", "NewJersey": "NJD", "NYIslanders": "NYI", "NYRangers": "NYR", "Ottawa": "OTT",
    "Philadelphia": "PHI", "Pittsburgh": "PIT", "SanJose": "SJS", "Seattle": "SEA", "St.Louis": "STL",
    "TampaBay": "TBL", "Toronto": "TOR", "Vancouver": "VAN", "Vegas": "VGK", "Washington": "WSH",
    "Winnipeg": "WPG", "Atlanta": "ATL", "Utah": "UTA", "Arizonas": "ARI", "SeattleKraken": "SEA",
    "Tampa": "TBL", "LA": "LAK", "WinnipegJets": "WPG",
}


def num(x):
    x = x.strip().lower()
    if x in ("pk", "ev", "even"):
        return 100.0
    try:
        return float(x.replace("½", ".5"))
    except ValueError:
        return None


def parse(html, start_year):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    cells = [[re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
             for r in rows]
    # newer pages have 2 puck-line cells before the totals; index totals from the end
    cells = [c for c in cells if len(c) >= 14 and c[2] in ("V", "H")]
    out = []
    for v, h in zip(cells[::2], cells[1::2]):
        if v[2] != "V" or h[2] != "H":
            continue
        mmdd = int(v[0])
        year = start_year if mmdd >= 800 else start_year + 1
        out.append({
            "gameDate": year * 10000 + mmdd,
            "away": TEAMS.get(v[3].replace(" ", ""), v[3]), "home": TEAMS.get(h[3].replace(" ", ""), h[3]),
            "away_final": num(v[7]), "home_final": num(h[7]),
            "open_total": num(v[-4]), "open_over": num(v[-3]), "open_under": num(h[-3]),
            "close_total": num(v[-2]), "close_over": num(v[-1]), "close_under": num(h[-1]),
        })
    return out


def fetch_all():
    rows = []
    for slug, y in PAGES.items():
        req = urllib.request.Request(URL.format(slug), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as f:
            got = parse(f.read().decode("utf-8", "replace"), y)
        print(slug, len(got), "games")
        rows += got
        time.sleep(2)
    pd.DataFrame(rows).to_csv(SBR, index=False)


if __name__ == "__main__":
    fetch_all()
