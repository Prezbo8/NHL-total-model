"""'Other' goals by game type (suggestion #5, Oct 16 2026). Each team's projection includes a flat league-average part
for everything outside 5v5 and its own power play: 4v4, 3-on-3 overtime, empty nets, shorthanded goals and the shootout
winner's goal (split_model: other / 2 + EXTRA / 2, the same for every team). Close games go to overtime more often;
favourites score more empty-netters. Does that part depend on the matchup?

Actual per team-game: goals - 5v5 goals - its 5on4 goals. Projected: the live flat part (as it enters the projection,
after goalie / back-to-back / speed scaling). Variants fitted on 2021-23, judged on 2023-26:
  A. flat (live)
  B. depends on the projected gap |lam_h - lam_a| (game total of the part), split evenly
  C. B + the favourite's share: team part = total part x (0.5 + s x (own lam - opp lam) / (lam_h + lam_a))
Team-goal deviance (lower = better) and the miss of the part itself by gap fifth.

  python3 research/studies/other_goals.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import split_model as sm
from injury_top5 import dev


def table():
    games = sm.load_split()
    p = sm.walk_split(games, known_starters=False, record_detail=True)
    x = p.merge(games[["gameId", "hg", "ag", "ev_goalsFor", "ev_goalsAgainst", "pp_goalsFor", "pk_goalsAgainst"]], on="gameId")
    x = x[x.season >= 2021].copy()
    for sd in ("home", "away"):
        x[f"{sd}_part"] = x[f"{sd}_oth"] * (1 + x[f"{sd}_gadj"]) * (1 + x[f"{sd}_b2badj"]) * (1 + x[f"{sd}_spd"])
    x["h_act"] = x.hg - x.ev_goalsFor - x.pp_goalsFor
    x["a_act"] = x.ag - x.ev_goalsAgainst - x.pk_goalsAgainst
    x["gap"] = (x.lam_h - x.lam_a).abs()
    x["rel"] = (x.lam_h - x.lam_a) / (x.lam_h + x.lam_a)  # home's edge, -1..1
    return x


def project(x, a, b, s):
    """Each team's new lam: the live part swapped for (a + b x gap) x (0.5 +/- s x rel)."""
    tot = a + b * x.gap
    return (x.lam_h - x.home_part + tot * (0.5 + s * x.rel), x.lam_a - x.away_part + tot * (0.5 - s * x.rel))


def score(x, lh, la):
    return np.concatenate([dev(x.hg, lh), dev(x.ag, la)]).mean()


def main():
    x = table()
    tr, te = x[x.season.between(2021, 2022)], x[x.season.between(2023, 2025)]
    print(f"{len(x)} games 2021-26. Live part per game {(x.home_part + x.away_part).mean():.3f}, actual {(x.h_act + x.a_act).mean():.3f}")
    print("\nactual vs live part (game total) by projected gap fifth:")
    for lab, s in (("2021-23", tr), ("2023-26", te)):
        q = pd.qcut(s.gap, 5, labels=False)
        print(f"   {lab}: " + "  ".join(f"gap {s.gap[q == i].mean():.2f}: act {(s.h_act + s.a_act)[q == i].mean():.3f} / live {(s.home_part + s.away_part)[q == i].mean():.3f}"
                                    for i in range(5)))
    print("\nfavourite's share of the part (actual), by home edge fifth:")
    for lab, s in (("2021-23", tr), ("2023-26", te)):
        q = pd.qcut(s.rel, 5, labels=False)
        print(f"   {lab}: " + "  ".join(f"edge {s.rel[q == i].mean():+.2f}: home {s.h_act[q == i].mean():.3f} away {s.a_act[q == i].mean():.3f}" for i in range(5)))
    # fit on 2021-23
    flat = (tr.h_act + tr.a_act).mean()
    bb = np.polyfit(tr.gap, tr.h_act + tr.a_act, 1)
    grid_s = np.round(np.arange(0, 1.51, 0.05), 2)
    s_best = min(grid_s, key=lambda s: score(tr, *project(tr, bb[1], bb[0], s)))
    live = lambda d: (d.lam_h, d.lam_a)
    print("\nteam-goal deviance (lower = better), fitted on 2021-23:")
    for name, f in (("A. flat, live", live),
                    (f"A2. flat refit ({flat:.3f})", lambda d: project(d, flat, 0, 0)),
                    (f"B. {bb[1]:.3f} {bb[0]:+.3f} x gap, even", lambda d: project(d, bb[1], bb[0], 0)),
                    (f"C. B + favourite share s = {s_best}", lambda d: project(d, bb[1], bb[0], s_best)),
                    (f"C2. flat + favourite share s = {s_best}", lambda d: project(d, flat, 0, s_best))):
        print(f"   {name:40s} 2021-23 {score(tr, *f(tr)):.5f}   2023-26 {score(te, *f(te)):.5f}")


if __name__ == "__main__":
    main()
