"""Faceoffs: does a team's faceoff record make the projection more accurate?

Per-game faceoffs by zone from the NHL stats API (research/lib/faceoffs_hist.py -> data/faceoffs.csv). For every
team-game 2021-26, each team's faceoff rates from earlier games this season only (shrunk toward league average by
K faceoffs), then:
  - overall faceoff % (own - opponent's): can only move WHO scores (the two teams' wins add to 100%), not the total
  - offensive-zone draws: own offensive-zone win % vs the opponent's defensive-zone win % (the same draws), the one
    faceoff signal that can raise or lower a game's total
  0. is it a skill? team faceoff % in the first half of a season vs the second half
  1. slope of the team-goal miss (goals / projected - 1) on each feature, 2021-23 and 2023-26 separately
  2. each team's own goals: mean absolute miss, root-mean-square miss, Poisson log loss, both halves
  3. accuracy, size fitted on 2021-23, judged on 2023-26: team-goal deviance (lower = better), log loss of the
     over/under lean vs closing and opening lines (2024-26), then the flag-rule bets 2021-26

  python3 research/studies/faceoffs.py      # needs data/faceoffs.csv (research/lib/faceoffs_hist.py)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import odds
import paths
import split_model as sm
from compare import score
from injury_backtest import team_dev
from recency_ratings import bets

KS = (100, 300)  # shrink: faceoffs of league average mixed into each team's rate


def rates(fo, k):
    """Per (gameId, home 'H'/'R'): the team's faceoff rates from its earlier games this season, shrunk by k."""
    fo = fo.copy()
    fo["season"] = fo.gameId // 1000000
    for c, n in (("all", "totalFaceoffs"), ("oz", "offensiveZoneFaceoffs"), ("dz", "defensiveZoneFaceoffs")):
        p = {"all": "faceoffWinPct", "oz": "offensiveZoneFaceoffPct", "dz": "defensiveZoneFaceoffPct"}[c]
        fo[f"{c}_w"], fo[f"{c}_n"] = fo[p].fillna(0) * fo[n], fo[n]
    lg = {c: fo[f"{c}_w"].sum() / fo[f"{c}_n"].sum() for c in ("all", "oz", "dz")}
    fo = fo.sort_values("gameId")
    out = []
    for (team, season), x in fo.groupby(["team", "season"]):
        x = x.copy()
        for c in ("all", "oz", "dz"):
            w, n = x[f"{c}_w"].cumsum().shift(1).fillna(0), x[f"{c}_n"].cumsum().shift(1).fillna(0)
            x[c] = (w + k * lg[c]) / (n + k) - lg[c]  # above (+) / below (-) league average, before this game
        out.append(x)
    return pd.concat(out)[["gameId", "homeRoad", "team", "season", "all", "oz", "dz"]]


def features(proj, fo_rates):
    h = fo_rates[fo_rates.homeRoad == "H"].set_index("gameId")
    a = fo_rates[fo_rates.homeRoad == "R"].set_index("gameId")
    x = proj.join(h[["all", "oz", "dz"]], on="gameId").join(a[["all", "oz", "dz"]], on="gameId", rsuffix="_a")
    x = x.dropna(subset=["all", "all_a"])
    x["fo_h"], x["fo_a"] = x["all"] - x.all_a, x.all_a - x["all"]           # overall: zero-sum
    x["oz_h"], x["oz_a"] = x.oz - x.dz_a, x.oz_a - x.dz                       # own offensive-zone draws vs their D-zone
    return x


def adjusted(p, x, b_fo, b_oz):
    q = p.set_index("gameId").copy()
    xx = x.set_index("gameId")
    q.loc[xx.index, "lam_h"] = q.loc[xx.index, "lam_h"] * (1 + b_fo * xx.fo_h + b_oz * xx.oz_h)
    q.loc[xx.index, "lam_a"] = q.loc[xx.index, "lam_a"] * (1 + b_fo * xx.fo_a + b_oz * xx.oz_a)
    q["proj"] = q.lam_h + q.lam_a
    return q.reset_index()


def slope(x, games, seasons, feats):
    d = x[x.season.between(*seasons)].merge(games[["gameId", "hg", "ag"]], on="gameId")
    y = np.r_[d.hg / d.lam_h - 1, d.ag / d.lam_a - 1]
    X = np.column_stack([np.r_[d[f + "_h"], d[f + "_a"]] for f in feats])
    return np.linalg.lstsq(np.column_stack([np.ones(len(y)), X]), y, rcond=None)[0][1:]


def team_metrics(p, games, seasons):
    """Each team's own goals vs its projection: mean absolute miss, root-mean-square miss, Poisson log loss."""
    x = p.merge(games[["gameId", "hg", "ag"]], on="gameId")
    x = x[x.season.between(*seasons)]
    y, lam = np.r_[x.hg, x.ag], np.r_[x.lam_h, x.lam_a]
    ll = (lam - y * np.log(lam) + np.array([np.sum(np.log(np.arange(1, k + 1))) for k in y.astype(int)])).mean()
    return np.abs(y - lam).mean(), np.sqrt(((y - lam) ** 2).mean()), ll


def main():
    games = sm.load_split()
    proj = sm.walk_split(games, known_starters=False)
    fo = pd.read_csv(paths.data("faceoffs.csv")).drop_duplicates(["gameId", "homeRoad"])
    side = games.set_index("gameId")[["home", "away"]]
    fo = fo[fo.gameId.isin(side.index)].copy()
    fo["team"] = np.where(fo.homeRoad == "H", side.home.reindex(fo.gameId).values, side.away.reindex(fo.gameId).values)
    print(f"faceoff team-games matched to model games: {len(fo)} of {len(games) * 2}")

    print("\n0. Is it a skill? team faceoff % first half vs second half of each season (correlation)")
    fo["season"] = fo.gameId // 1000000
    for c, p in (("overall", "faceoffWinPct"), ("offensive zone", "offensiveZoneFaceoffPct"), ("defensive zone", "defensiveZoneFaceoffPct")):
        r = []
        for s, x in fo[fo.season.between(2021, 2025)].groupby("season"):
            x = x.sort_values("gameId")
            x["half"] = x.groupby("team").cumcount() < 41
            t = x.groupby(["team", "half"])[p].mean().unstack()
            r.append(t.corr().iloc[0, 1])
        print(f"   {c:15s} {np.mean(r):.2f}  (by season: {', '.join(f'{v:.2f}' for v in r)})")

    for k in KS:
        x = features(proj, rates(fo, k))
        print(f"\n--- shrink {k} faceoffs ---")
        print("1. slope of team-goal miss (+0.10 = 10 points of faceoff % above average -> +1% goals)")
        for feats in (("fo",), ("oz",), ("fo", "oz")):
            s1, s2 = slope(x, games, (2021, 2022), feats), slope(x, games, (2023, 2025), feats)
            print(f"   {' + '.join(feats):8s} 2021-23 {', '.join(f'{v:+.3f}' for v in s1):16s} 2023-26 {', '.join(f'{v:+.3f}' for v in s2)}")
        print(f"2. each team's own goals (fit 2021-23): {'2021-23 MAE / RMSE / LL':>27s}   {'2023-26 MAE / RMSE / LL':>27s}")
        variants = [("model as is", proj)]
        for feats in (("fo",), ("oz",), ("fo", "oz")):
            b = dict(zip(feats, slope(x, games, (2021, 2022), feats)))
            variants.append(("+ " + " + ".join(feats), adjusted(proj, x, b.get("fo", 0.0), b.get("oz", 0.0))))
        for name, p in variants:
            a, c = team_metrics(p, games, (2021, 2022)), team_metrics(p, games, (2023, 2025))
            print(f"   {name:38s} {a[0]:.4f} / {a[1]:.4f} / {a[2]:.4f}    {c[0]:.4f} / {c[1]:.4f} / {c[2]:.4f}")
        print(f"3. accuracy (fit 2021-23)   {'team dev 23-26':>14s} {'LL close':>9s} {'LL open':>8s}   {'bets open':>11s}   {'bets close':>11s}")
        bo, bc = bets(proj)
        print(f"   {'model as is':24s} {team_dev(proj, games, (2023, 2025)):14.4f} {score(proj, odds.ODDS)[1]:9.4f} "
              f"{score(proj, odds.ODDS_OPEN)[1]:8.4f}   {bo}   {bc}")
        for feats in (("fo",), ("oz",), ("fo", "oz")):
            b = dict(zip(feats, slope(x, games, (2021, 2022), feats)))
            p = adjusted(proj, x, b.get("fo", 0.0), b.get("oz", 0.0))
            bo, bc = bets(p)
            print(f"   {'+ ' + ' + '.join(feats):24s} {team_dev(p, games, (2023, 2025)):14.4f} {score(p, odds.ODDS)[1]:9.4f} "
                  f"{score(p, odds.ODDS_OPEN)[1]:8.4f}   {bo}   {bc}")


if __name__ == "__main__":
    main()
