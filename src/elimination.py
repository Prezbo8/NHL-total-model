"""Teams already eliminated from the playoffs allow more goals than the model projects (research/studies/elimination.py:
+0.30 goals a game 2021-26, the same direction all 5 seasons; their own scoring a touch lower). Better accuracy in both
halves, only 7 SLAM / 1U calls changed in 5 seasons. A team is out on the NHL's 'e' flag or when it can't reach the
playoffs on points (8+ conference teams and 3+ division teams already above its maximum; matches the flag 344 of 363
team-days, the misses are tiebreakers caught a day or two later). Nothing happens before ~March.
"""
import json
import urllib.request

import model as m

SCORE, ALLOW = 0.99, 1.044  # out team's own goals / goals it allows (2021-26 walk-forward factors, shrunk halfway)
URL = "https://api-web.nhle.com/v1/standings/now"


def out_teams(rows=None):
    """Set of team abbreviations already eliminated, from the NHL standings (rows = the API's 'standings' list)."""
    if rows is None:
        rows = json.load(urllib.request.urlopen(m.fetch(URL), timeout=30))["standings"]
    t = [{"team": r["teamAbbrev"]["default"], "conf": r["conferenceAbbrev"], "div": r["divisionAbbrev"], "pts": r["points"],
          "maxp": r["points"] + 2 * (82 - r["gamesPlayed"]), "e": r.get("clinchIndicator") == "e"} for r in rows]
    out = set()
    for x in t:
        conf = [y for y in t if y["conf"] == x["conf"]]
        above = sum(y["pts"] > x["maxp"] for y in conf)
        above_div = sum(y["pts"] > x["maxp"] for y in conf if y["div"] == x["div"])
        if x["e"] or (above >= 8 and above_div >= 3):
            out.add(x["team"])
    return out


def factors(home_out, away_out):
    """(home goals factor, away goals factor): an out team scores x SCORE, and its opponent scores x ALLOW."""
    return (SCORE if home_out else 1.0) * (ALLOW if away_out else 1.0), (SCORE if away_out else 1.0) * (ALLOW if home_out else 1.0)
