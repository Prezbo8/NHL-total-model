"""Download NHL standings for every day from Feb 1 to the end of each regular season 2021-22 to 2025-26
(api-web.nhle.com/v1/standings/<date>, which carries the official clinch / eliminated flag as of that day)
into data/standings_hist.csv. Research only (research/studies/elimination.py).

  python3 research/lib/standings_hist.py
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
import pandas as pd

import model as m
import paths
import split_model as sm

URL = "https://api-web.nhle.com/v1/standings/{}"


def day(d):
    for _ in range(4):
        try:
            rows = json.load(urllib.request.urlopen(m.fetch(URL.format(d)), timeout=60))["standings"]
            break
        except Exception:
            continue
    else:
        raise RuntimeError(f"standings {d} failed")
    return [{"date": d, "team": r["teamAbbrev"]["default"], "conf": r["conferenceAbbrev"], "div": r["divisionAbbrev"],
             "gp": r["gamesPlayed"], "pts": r["points"], "clinch": r.get("clinchIndicator") or "",
             "conf_seq": r["conferenceSequence"]} for r in rows]


def main(first=2021, last=2025):
    g = sm.load_split()
    dates = []
    for s in range(first, last + 1):
        end = pd.to_datetime(str(g[g.season == s].gameDate.max()))
        dates += [d.strftime("%Y-%m-%d") for d in pd.date_range(f"{s + 1}-02-01", end)]
    with ThreadPoolExecutor(8) as ex:
        out = [r for rows in ex.map(day, dates) for r in rows]
    d = pd.DataFrame(out)
    print(f"{len(dates)} days, {len(d)} rows, eliminated rows {(d.clinch == 'e').sum()}")
    d.to_csv(paths.data("standings_hist.csv"), index=False)


if __name__ == "__main__":
    main()
