"""Follow-up to injury_top5.py: the injury adjustment fixes only about half the miss when a TOP-5 attacker / defender
is out. Test a bigger size for those players only: a missing top-5 attacker's effect on his team's goals x S_off,
a missing top-5 defender's effect on the opponent's goals x S_def; every other missing regular stays at the live
1.15x. Same data as injury_top5.py (who actually dressed, ratings from earlier seasons only).

Picked on 2021-23 (team-goal deviance), judged on 2023-26: team-goal deviance, the miss in top-5-out team-games,
log loss vs closing / opening lines (2024-26), then the flag-rule bets 2021-26.

  python3 research/studies/injury_top5_size.py      # needs data/dressed.csv (research/lib/lineups_hist.py)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import injuries
import odds
import paths
import split_model as sm
from compare import score
from injury_backtest import adjusted, team_dev
from injury_top5 import TOP, regulars
from recency_ratings import bets

SIZES = (1.15, 1.5, 2.0, 2.5, 3.0)


def effects(reg, s_off, s_def):
    """Missing players' (d_off, d_def) with top-5 ones scaled by s / live size (adjusted() applies the live 1.15x)."""
    out, top = {}, {}
    for k, v in reg.items():
        to = set(sorted(range(len(v)), key=lambda i: -v[i][0])[:TOP])
        td = set(sorted(range(len(v)), key=lambda i: -v[i][1])[:TOP])
        do = [v[i][0] * (s_off / injuries.SCALE if i in to else 1.0) for i in range(len(v)) if v[i][2]]
        dd = [v[i][1] * (s_def / injuries.SCALE if i in td else 1.0) for i in range(len(v)) if v[i][2]]
        out[k] = (do, dd)
        top[k] = (sum(v[i][2] for i in to), sum(v[i][2] for i in td))
    return out, top


def top_miss(p, games, top, seasons):
    """Average miss (actual - projected) for a team's goals when a top-5 attacker of its own / top-5 defender of the
    opponent's is out."""
    x = p.merge(games[["gameId", "hg", "ag"]], on="gameId")
    x = x[x.season.between(*seasons)]
    off, dfn = [], []
    for r in x.itertuples():
        th, ta = top.get((r.gameId, r.home)), top.get((r.gameId, r.away))
        if th is None or ta is None:
            continue
        for t, o, y, lam in ((th, ta, r.hg, r.lam_h), (ta, th, r.ag, r.lam_a)):
            if t[0]:
                off.append(y - lam)
            if o[1]:
                dfn.append(y - lam)
    return np.mean(off), np.mean(dfn)


def main():
    games = sm.load_split()
    base = sm.walk_split(games, known_starters=False)
    reg = regulars(games, pd.read_csv(paths.data("dressed.csv")))
    grid = []
    for so in SIZES:
        for sd in SIZES:
            eff, top = effects(reg, so, sd)
            p = adjusted(base, eff, scale=injuries.SCALE)
            grid.append((so, sd, p, top, team_dev(p, games, (2021, 2022))))
    best = min(grid, key=lambda g: g[4])
    print(f"Picked on 2021-23 (team-goal deviance): top-5 attackers x{best[0]}, top-5 defenders x{best[1]}\n")
    print(f"{'top-5 size (attack / defense)':30s} {'dev 21-23':>9s} {'dev 23-26':>9s} {'att-out miss 23-26':>18s} {'def-out miss 23-26':>18s}"
          f" {'LL close':>9s} {'LL open':>8s}   {'bets open':>11s}   {'bets close':>11s}")
    for so, sd, p, top, d1 in grid:
        if not (so == sd or (so, sd) == best[:2] or so == 1.15 or sd == 1.15):
            continue
        mo, md = top_miss(p, games, top, (2023, 2025))
        bo, bc = bets(p)
        name = f"x{so} / x{sd}" + ("  (live)" if so == sd == 1.15 else "") + ("  <- picked" if (so, sd) == best[:2] else "")
        print(f"{name:30s} {d1:9.4f} {team_dev(p, games, (2023, 2025)):9.4f} {mo:+18.3f} {md:+18.3f}"
              f" {score(p, odds.ODDS)[1]:9.4f} {score(p, odds.ODDS_OPEN)[1]:8.4f}   {bo}   {bc}")
    print("\n(att-out miss: a team's goals minus projected when one of its top-5 attackers is out; def-out: the opponent's"
          " goals when a top-5 defender is out; teams with nobody out miss by about +0.03 / +0.01 in 2023-26)")


if __name__ == "__main__":
    main()
