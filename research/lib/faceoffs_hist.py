"""Download every regular-season team-game's faceoffs (NHL stats API, by zone) 2020-21 to now into data/faceoffs.csv.
Research only (research/studies/faceoffs.py).

  python3 research/lib/faceoffs_hist.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
import pandas as pd

import model as m
import paths

# sorted by game + team: without a fixed sort the API's pages overlap (rows repeated, others missing)
SORT = urllib.parse.quote('[{"property":"gameId","direction":"ASC"},{"property":"teamId","direction":"ASC"}]')
URL = "https://api.nhle.com/stats/rest/en/team/faceoffpercentages?isAggregate=false&isGame=true&start={}&limit=100&sort=" + SORT + "&cayenneExp={}"
COLS = ["gameId", "homeRoad", "totalFaceoffs", "faceoffWinPct", "offensiveZoneFaceoffs", "offensiveZoneFaceoffPct",
        "defensiveZoneFaceoffs", "defensiveZoneFaceoffPct", "neutralZoneFaceoffs", "neutralZoneFaceoffPct"]


def season(s):
    q = urllib.parse.quote(f"seasonId={s}{s + 1} and gameTypeId=2")
    rows, start = [], 0
    while True:
        d = json.load(urllib.request.urlopen(m.fetch(URL.format(start, q)), timeout=60))
        rows += d["data"]
        start += 100
        if start >= d["total"]:
            return rows


def main(first=2020, last=2026):
    out = []
    for s in range(first, last + 1):
        r = season(s)
        print(f"{s}: {len(r)} team-games")
        out += r
    d = pd.DataFrame(out)[COLS]
    print(f"{len(d)} rows, {d.duplicated(['gameId', 'homeRoad']).sum()} repeated")
    d.to_csv(paths.data("faceoffs.csv"), index=False)


if __name__ == "__main__":
    main()
