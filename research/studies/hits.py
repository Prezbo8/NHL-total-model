"""Hits: does a team's hitting make the projection more accurate (game totals and each team's own goals)?

Hits for / against per game from MoneyPuck's game file (all situations). For every team-game 2021-26, each team's
hits per game from its earlier games this season only (shrunk toward league average by K games), centered on
league average. Rink scorers count hits very differently, so a second version uses road games only.
Features for a team's goals in a game:
  own : the team's hits for + hits against (how physical its games are; hitting teams usually lack the puck)
  opp : the opponent's same number
  game: own + opp (a physical matchup -> fewer goals for BOTH teams = the one that can move the total)
  0. is it a team trait? first half vs second half of each season (correlation), all games and road only
  1. slope of the team-goal miss (goals / projected - 1) per 10 hits a game, 2021-23 and 2023-26
  2. each team's own goals: mean absolute miss, RMSE, Poisson log loss (fit 2021-23), both halves
  3. game totals: team-goal deviance 2023-26, log loss vs closing / opening lines, flag-rule bets 2021-26

  python3 research/studies/hits.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import model as m
import odds
import split_model as sm
from compare import score
from faceoffs import team_metrics
from injury_backtest import team_dev
from recency_ratings import bets

K = 10  # games of league average mixed into each team's hits rate
FEATS = (("game",), ("own", "opp"))


def load_hits(games):
    d = pd.read_csv(m.DATA, usecols=["gameId", "situation", "home_or_away", "playoffGame", "hitsFor", "hitsAgainst"])
    d = d[(d.playoffGame == 0) & (d.situation == "all")].drop_duplicates(["gameId", "home_or_away"])
    d = d[d.gameId.isin(games.gameId)]
    side = games.set_index("gameId")
    d["team"] = np.where(d.home_or_away == "HOME", side.home.reindex(d.gameId).values, side.away.reindex(d.gameId).values)
    d["season"] = side.season.reindex(d.gameId).values
    d["phys"] = d.hitsFor + d.hitsAgainst
    return d.sort_values("gameId")


def rates(h, road_only):
    lg = h.phys.mean()
    out = []
    for _, x in h.groupby(["team", "season"]):
        x = x.copy()
        use = (x.home_or_away == "AWAY") if road_only else pd.Series(True, index=x.index)
        s = (x.phys * use).cumsum().shift(1).fillna(0)
        n = use.astype(int).cumsum().shift(1).fillna(0)
        x["rate"] = (s + K * lg) / (n + K) - lg  # hits a game above (+) / below (-) league average, before this game
        out.append(x)
    r = pd.concat(out)
    return r[r.home_or_away == "HOME"].set_index("gameId").rate, r[r.home_or_away == "AWAY"].set_index("gameId").rate


def features(proj, h, road_only):
    rh, ra = rates(h, road_only)
    x = proj.join(rh.rename("rh"), on="gameId").join(ra.rename("ra"), on="gameId").dropna(subset=["rh", "ra"])
    x["own_h"], x["opp_h"], x["own_a"], x["opp_a"] = x.rh / 10, x.ra / 10, x.ra / 10, x.rh / 10   # per 10 hits a game
    x["game_h"] = x["game_a"] = (x.rh + x.ra) / 10
    return x


def slope(x, games, seasons, feats):
    d = x[x.season.between(*seasons)].merge(games[["gameId", "hg", "ag"]], on="gameId")
    y = np.r_[d.hg / d.lam_h - 1, d.ag / d.lam_a - 1]
    X = np.column_stack([np.r_[d[f + "_h"], d[f + "_a"]] for f in feats])
    return np.linalg.lstsq(np.column_stack([np.ones(len(y)), X]), y, rcond=None)[0][1:]


def adjusted(p, x, b):
    q, xx = p.set_index("gameId").copy(), x.set_index("gameId")
    for s in ("h", "a"):
        q.loc[xx.index, f"lam_{s}"] = q.loc[xx.index, f"lam_{s}"] * (1 + sum(v * xx[f"{f}_{s}"] for f, v in b.items()))
    q["proj"] = q.lam_h + q.lam_a
    return q.reset_index()


def main():
    games = sm.load_split()
    proj = sm.walk_split(games, known_starters=False)
    h = load_hits(games)
    print(f"hits team-games matched: {len(h)} of {len(games) * 2}; league average {h.phys.mean():.1f} hits a game "
          f"(both teams' hits in a team's games)")

    print("\n0. Is it a team trait? hits in a team's games, first half vs second half of each season (correlation)")
    for name, road in (("all games", False), ("road games only", True)):
        r = []
        for _, x in h[h.season.between(2021, 2025)].groupby("season"):
            x = x[x.home_or_away == "AWAY"] if road else x
            x = x.assign(half=x.groupby("team").cumcount() < x.groupby("team").team.transform("size") / 2)
            r.append(x.groupby(["team", "half"]).phys.mean().unstack().corr().iloc[0, 1])
        print(f"   {name:16s} {np.mean(r):.2f}  (by season: {', '.join(f'{v:.2f}' for v in r)})")
    home = h[h.home_or_away == "HOME"].groupby(["season", "team"]).phys.mean()
    away = h[h.home_or_away == "AWAY"].groupby(["season", "team"]).phys.mean()
    print(f"   rink effect: a team's home games vs its road games, spread (sd) of the difference {(home - away).std():.1f} hits a game")

    for name, road in (("ALL GAMES", False), ("ROAD GAMES ONLY (no rink scorer bias)", True)):
        x = features(proj, h, road)
        print(f"\n--- {name} ---")
        print("1. slope of team-goal miss per 10 hits a game above average (-0.02 = 2% fewer goals)")
        for feats in FEATS:
            s1, s2 = slope(x, games, (2021, 2022), feats), slope(x, games, (2023, 2025), feats)
            print(f"   {' + '.join(feats):10s} 2021-23 {', '.join(f'{v:+.3f}' for v in s1):16s} 2023-26 {', '.join(f'{v:+.3f}' for v in s2)}")
        variants = [("model as is", proj)] + [("+ " + " + ".join(f), adjusted(proj, x, dict(zip(f, slope(x, games, (2021, 2022), f)))))
                                             for f in FEATS]
        print(f"2. each team's own goals (fit 2021-23): {'2021-23 MAE / RMSE / LL':>27s}   {'2023-26 MAE / RMSE / LL':>27s}")
        for vn, p in variants:
            a, c = team_metrics(p, games, (2021, 2022)), team_metrics(p, games, (2023, 2025))
            print(f"   {vn:38s} {a[0]:.4f} / {a[1]:.4f} / {a[2]:.4f}    {c[0]:.4f} / {c[1]:.4f} / {c[2]:.4f}")
        print(f"3. game totals                 {'team dev 23-26':>14s} {'LL close':>9s} {'LL open':>8s}   {'bets open':>11s}   {'bets close':>11s}")
        for vn, p in variants:
            bo, bc = bets(p)
            print(f"   {vn:27s} {team_dev(p, games, (2023, 2025)):14.4f} {score(p, odds.ODDS)[1]:9.4f} {score(p, odds.ODDS_OPEN)[1]:8.4f}   {bo}   {bc}")


if __name__ == "__main__":
    main()
