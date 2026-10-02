"""Skater injury adjustment.

Injured / suspended regulars (ESPN's injury list) are removed from their team and replaced by a
replacement-level skater, using each player's value from players.player_table():

  offense: team scores  (1 - share x (player offense - replacement offense) x in_rating)
  defense: opponent scores (1 + share x (replacement defense - player defense) x in_rating)

share     = his ice time per game / all skater ice time in a game (5 skaters x 60 min)
in_rating = how much of him is actually in the team's current rating: a player who has already
            missed most of the team's games is mostly gone from the numbers, so he's mostly not
            removed again (no double counting).

Not backtested (there's no free history of who was out each night) - shown on the dashboard so its
effect is visible.
"""
import json
import urllib.request

import pandas as pd

import model as m
import players
from teams import TEAMS

ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"
OUT_STATUSES = {"Out", "Injured Reserve", "Suspension"}  # Day-To-Day players usually play: shown, not adjusted
SKATER_SECONDS = 5 * 3600
K = m.K  # games of prior weight in the team ratings (same as the model)


def fetch():
    """[{team, name, pos, status, ret, note}] from ESPN; team = NHL abbreviation."""
    by_name = {m.norm_name(v): k for k, v in TEAMS.items()}
    with urllib.request.urlopen(m.fetch(ESPN), timeout=30) as f:
        data = json.load(f)
    rows = []
    for t in data.get("injuries", []):
        team = by_name.get(m.norm_name(t.get("displayName", "")))
        if not team:
            continue
        for i in t.get("injuries", []):
            a = i.get("athlete", {})
            pos = a.get("position", {}).get("abbreviation", "")
            if pos == "G":  # goalies are handled through the starting goalie
                continue
            rows.append({"team": team, "name": a.get("displayName", ""), "pos": pos, "status": i.get("status", ""),
                         "ret": (i.get("details") or {}).get("returnDate"), "note": i.get("shortComment", "")})
    return rows


def adjustments(injured, season, team_games):
    """{team: {"off": mult on its goals, "def": mult on its opponents' goals, "out": [(name, goals)], "dtd": [names]}}
    team_games: {team: games played this season} (for how much of each player is in the rating)."""
    pt = players.player_table(season)
    pt["key"] = pt.name.map(m.norm_name)
    out = {}
    for r in injured:
        o = out.setdefault(r["team"], {"off": 1.0, "def": 1.0, "out": [], "dtd": []})
        if r["status"] not in OUT_STATUSES:
            if r["status"] == "Day-To-Day":
                o["dtd"].append(r["name"])
            continue
        cand = pt[pt.key == m.norm_name(r["name"])]
        if len(cand) > 1:  # same name (two Sebastian Ahos): prefer the one on this team
            same = cand[(cand.team_cur == r["team"]) | (cand.team_last == r["team"]) | (cand.team == r["team"])]
            cand = same if len(same) else cand
        if cand.empty:
            continue  # no NHL history since 2020 (prospect/depth player): nothing to remove
        p = cand.iloc[0]
        n = team_games.get(r["team"], 0)
        w_cur = p.gp_cur / n if n and p.team_cur == r["team"] else 0.0
        w_last = min(p.gp_last / 82, 1.0) if p.team_last == r["team"] else 0.0
        in_rating = (K * w_last + n * w_cur) / (K + n)
        share = p.toi_pg / SKATER_SECONDS
        d_off = share * (p.f - players.REPLACEMENT[0]) * in_rating
        d_def = share * (players.REPLACEMENT[1] - p.a) * in_rating
        if abs(d_off) + abs(d_def) < 0.002:  # depth player / long gone: not worth listing
            continue
        o["off"] *= 1 - d_off
        o["def"] *= 1 + d_def
        o["out"].append((r["name"], d_off, d_def))
    return out


def team_games_this_season(games, season):
    g = games[games.season == season]
    return pd.concat([g.home, g.away]).value_counts().to_dict()
