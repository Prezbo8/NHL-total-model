"""Team skating speed (NHL EDGE): how often a team's skaters hit 20+ mph per game.

Each team's rating for a season is its PREVIOUS season's bursts per game, as a z-score vs the league
(known before every game; Arizona's carries over to Utah). Fitted on 2022-26 (5,248 games): a team
scores +2.0% per SD of its own speed and its opponent -1.7% (net +0.4% on the game total per SD).
"""
import json
import os
import time
import urllib.request

import pandas as pd

import model as m
import paths

SPEED = paths.data("team_speed.csv")
SPEED_DETAIL = "https://api-web.nhle.com/v1/edge/team-skating-speed-detail/{}/{}/2"
TEAMS_URL = "https://api.nhle.com/stats/rest/en/team"
CARRY = {"ARI": "UTA"}  # franchise moves: last season's speed belongs to the new team


def refresh(season):
    """Download one season's team speed (NHL EDGE) into data/team_speed.csv (idempotent)."""
    have = pd.read_csv(SPEED) if os.path.exists(SPEED) else pd.DataFrame(columns=["season", "team"])
    if (have.season == season).sum() >= 30:
        return
    ids = {t["triCode"]: t["id"] for t in json.load(urllib.request.urlopen(m.fetch(TEAMS_URL), timeout=30))["data"]}
    try:  # only teams that exist now (the NHL team list also has defunct franchises)
        current = {r["teamAbbrev"]["default"] for r in json.load(urllib.request.urlopen(
            m.fetch("https://api-web.nhle.com/v1/standings/now"), timeout=30)).get("standings", [])}
    except Exception:
        current = set()
    rows = []
    for abbr in sorted(current or ids):
        if abbr not in ids:
            continue
        try:
            d = json.load(urllib.request.urlopen(m.fetch(SPEED_DETAIL.format(ids[abbr], season * 10000 + season + 1)), timeout=30))
            a = next(x for x in d["skatingSpeedDetails"] if x["positionCode"] == "all")
            rows.append({"season": season, "team": abbr, "bursts22": a["burstsOver22"]["value"],
                         "bursts20_22": a["bursts20To22"]["value"], "bursts18_20": a["bursts18To20"]["value"],
                         "max_mph": a["maxSkatingSpeed"]["imperial"]})
        except Exception as e:
            print(f"  (speed: skipped {abbr} {season}: {e})")
        time.sleep(0.2)
    if rows:
        pd.concat([have[have.season != season], pd.DataFrame(rows)], ignore_index=True).to_csv(SPEED, index=False)


def z_prev(games):
    """{(season, team): z-score of that team's PREVIOUS season speed} for every season in the speed file + 1."""
    if not os.path.exists(SPEED):
        return {}
    sp = pd.read_csv(SPEED)
    n = pd.concat([games[["season", "home"]].rename(columns={"home": "team"}),
                   games[["season", "away"]].rename(columns={"away": "team"})]).value_counts().rename("n").reset_index()
    sp = sp.merge(n, on=["season", "team"], how="left")
    sp["n"] = sp.n.fillna(82)
    sp["fast"] = (sp.bursts22 + sp.bursts20_22) / sp.n
    sp["z"] = sp.groupby("season").fast.transform(lambda v: (v - v.mean()) / v.std())
    return {(s + 1, CARRY.get(t, t)): float(z) for s, t, z in zip(sp.season, sp.team, sp.z)}
