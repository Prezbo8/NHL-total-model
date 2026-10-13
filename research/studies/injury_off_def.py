"""Injury adjustment split in two: does the OFFENSE side (team scores less when an attacker sits) and the DEFENSE side
(opponent scores more when a defender sits) each hold up on its own?

Same data as injury_backtest.py (who actually dressed, 2021-26, ratings from seasons before the game only). Two checks:
  1. goals vs model regressed on both sides at once: slope per side (1.0 = right size, 0 = no effect), per period
  2. projection accuracy (team-goal deviance, lower = better; log loss vs closing / opening totals) with
     offense only, defense only, both, and each side at other sizes (live: both at 1.15x)

  python3 research/studies/injury_off_def.py      # needs data/dressed.csv (research/lib/lineups_hist.py download)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import compare
import odds
import paths
import split_model as sm
from injury_backtest import missing_effects, team_dev


def adjusted(base, eff, s_off, s_def, min_effect=0.002):
    """Projections with the offense side at s_off x and the defense side at s_def x."""
    p = base.copy()
    mult = {}
    for k, (do, dd) in eff.items():
        off = deff = 1.0
        for a, b in zip(do, dd):
            if abs(a) + abs(b) < min_effect:
                continue
            off *= 1 - s_off * a
            deff *= 1 + s_def * b
        mult[k] = (off, deff)
    one = (1.0, 1.0)
    p["lam_h"] = [lh * mult.get((g, h), one)[0] * mult.get((g, a), one)[1] for g, h, a, lh in zip(p.gameId, p.home, p.away, p.lam_h)]
    p["lam_a"] = [la * mult.get((g, a), one)[0] * mult.get((g, h), one)[1] for g, h, a, la in zip(p.gameId, p.home, p.away, p.lam_a)]
    p["proj"] = p.lam_h + p.lam_a
    return p


def slopes(t):
    """Least-squares slopes of goals-vs-model on both sides at once (+ intercept), with standard errors."""
    X = np.column_stack([np.ones(len(t)), t.own_off, t.opp_def]).astype(float)
    y = t.resid_pct.to_numpy(float)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ b
    se = np.sqrt(np.diag(res.var(ddof=3) * np.linalg.inv(X.T @ X)))
    return b[1], se[1], b[2], se[2]


def main():
    games = sm.load_split()
    dressed = pd.read_csv(paths.data("dressed.csv"))
    base = sm.walk_split(games, known_starters=False)
    eff = missing_effects(games, dressed)

    x = base.merge(games[["gameId", "hg", "ag"]], on="gameId")
    rows = []
    for r in x.itertuples():
        for team, opp, goals, lam in ((r.home, r.away, r.hg, r.lam_h), (r.away, r.home, r.ag, r.lam_a)):
            if (r.gameId, team) in eff and (r.gameId, opp) in eff:
                rows.append((r.season, goals / lam - 1, -sum(eff[(r.gameId, team)][0]), sum(eff[(r.gameId, opp)][1])))
    t = pd.DataFrame(rows, columns=["season", "resid_pct", "own_off", "opp_def"])
    t = t[t.season >= 2021]
    print(f"team-games: {len(t)} | avg offense removed {t.own_off.mean():+.2%} (sd {t.own_off.std():.2%}) | "
          f"avg defense added {t.opp_def.mean():+.2%} (sd {t.opp_def.std():.2%})")
    print("\n1. Slopes, both sides fitted together (1.0 = right size, 0 = no effect; ± = 1 standard error)")
    for name, u in (("2021-26", t), ("2021-24", t[t.season.between(2021, 2023)]), ("2024-26", t[t.season.between(2024, 2025)]),
                    *((f"{s}-{str(s + 1)[2:]}", t[t.season == s]) for s in range(2021, 2026))):
        bo, so, bd, sd = slopes(u)
        print(f"   {name:8s} offense {bo:5.2f} ± {so:.2f}   defense {bd:5.2f} ± {sd:.2f}   ({len(u)} team-games)")

    print(f"\n2. Accuracy {'':26s} {'team dev 21-26':>14s} {'team dev 24-26':>14s} {'LL close':>9s} {'LL open':>8s}")
    for name, so, sd in (("no adjustment", 0, 0), ("live: both 1.15x", 1.15, 1.15), ("offense only 1.15x", 1.15, 0),
                         ("defense only 1.15x", 0, 1.15), ("offense 1.15x, defense 0.5x", 1.15, 0.5),
                         ("offense 1.15x, defense 2x", 1.15, 2.0), ("offense 1.5x, defense 1.15x", 1.5, 1.15)):
        p = adjusted(base, eff, so, sd)
        print(f"   {name:36s} {team_dev(p, games, (2021, 2025)):14.4f} {team_dev(p, games, (2024, 2025)):14.4f} "
              f"{compare.score(p, odds.ODDS)[1]:9.4f} {compare.score(p, odds.ODDS_OPEN)[1]:8.4f}")


if __name__ == "__main__":
    main()
