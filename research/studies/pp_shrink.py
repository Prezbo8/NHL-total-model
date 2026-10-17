"""Separate shrink for the power-play / penalty-kill ratings (suggestion #3, Oct 16 2026). PP and PK ratings are built
from ~6-8 minutes a game vs ~48 at 5v5, so they are much noisier, but they share the 5v5 settings: K = 15 games of
last season's prior, REGRESS = 0.33 summer pull to league average. rating_shrink.py (Oct 10) moved both together for
every rating; this moves them for PP / PK only (split_model.walk_split pp_k / pp_regress; drawn / taken unchanged).
Result: K = 25 (REGRESS unchanged) better on both halves and early-season -> live as model.K_PP on Oct 16 2026.

Judged on projection accuracy first: team-goal deviance (lower = better) 2021-23 and 2023-26 separately, the same for
the first 20 games of each team's season (where the prior matters most), log loss of the over/under lean vs closing
and opening lines 2024-26; then the flag-rule bets (open / close, 2021-26).

  python3 research/studies/pp_shrink.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np

import model as m
import odds
import split_model as sm
from compare import score
from injury_top5 import dev
from recency_ratings import bets

GRID = [(None, None)] + [(k, r) for k in (15, 25, 40, 60) for r in (0.33, 0.5, 0.66) if (k, r) != (15, 0.33)]


def early(p, games):
    """Each game's 'early' flag: either team within its first 20 games of the season."""
    n = {}
    flag = []
    for r in p.sort_values(["gameDate", "gameId"]).itertuples():
        a, b = n.get((r.season, r.home), 0), n.get((r.season, r.away), 0)
        flag.append((r.gameId, a < 20 or b < 20))
        n[(r.season, r.home)], n[(r.season, r.away)] = a + 1, b + 1
    return dict(flag)


def devs(p, games, seasons, only=None):
    x = p.merge(games[["gameId", "hg", "ag"]], on="gameId")
    x = x[x.season.between(*seasons)]
    if only is not None:
        x = x[x.gameId.map(only)]
    return np.concatenate([dev(x.hg, x.lam_h), dev(x.ag, x.lam_a)]).mean()


def main():
    games = sm.load_split()
    print(f"{'PP/PK K':>7s} {'REGRESS':>7s} | {'dev 21-23':>9s} {'dev 23-26':>9s} | {'early 21-23':>11s} {'early 23-26':>11s} | "
          f"{'LL close':>8s} {'LL open':>8s} | {'bets open':>11s}   {'bets close':>11s}")
    ef = None
    for k, reg in GRID:
        p = sm.walk_split(games, known_starters=False, pp_k=k, pp_regress=reg)
        ef = ef or early(p, games)
        bo, bc = bets(p)
        tag = "  <- live (since Oct 16 2026)" if k == m.K_PP and reg == m.REGRESS else "  <- before Oct 16 2026" if k is None else ""
        print(f"{k or m.K:7d} {reg if reg is not None else m.REGRESS:7.2f} | {devs(p, games, (2021, 2022)):9.5f} {devs(p, games, (2023, 2025)):9.5f} | "
              f"{devs(p, games, (2021, 2022), ef):11.5f} {devs(p, games, (2023, 2025), ef):11.5f} | "
              f"{score(p, odds.ODDS)[1]:8.4f} {score(p, odds.ODDS_OPEN)[1]:8.4f} | {bo}   {bc}{tag}")


if __name__ == "__main__":
    main()
