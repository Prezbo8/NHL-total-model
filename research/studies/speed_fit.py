"""Where the team-speed numbers come from (Nov 2026 audit, item 1.7): model.SPEED_OWN (+2.0% own scoring per SD of own
speed) and SPEED_OPP (-1.7% to the opponent's scoring per SD), "fitted on 2022-26", had no script.

Each team-game: actual goals vs the projection made WITHOUT speed (walk_split use_speed=False), against both teams'
speed ratings (speed.z_prev: last season's 20+ mph bursts per game, z-scored; known before the season). Fitted as
goals ~ Poisson(projection x (1 + own x z_own + opp x z_opp)). Prints: the fit on all of 2022-26 with a 90% range
(1,000 resamples of game nights), the fit on each season alone, and walk-forward (each season scored with numbers
fitted on the seasons before it): team-goal deviance with no speed, the live numbers and the walk-forward fit.

  python3 research/studies/speed_fit.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers

from judge import dev  # first: puts src/ on the path

import numpy as np
import pandas as pd

import model as m
import speed
import split_model as sm


def rows(games):
    """One row per team-game from 2022-23 on: goals, projection without speed, own / opponent speed z, season, night."""
    p = sm.walk_split(games, known_starters=False, use_speed=False).merge(games[["gameId", "hg", "ag"]], on="gameId")
    z = speed.z_prev(games)
    out = []
    for side, opp, g, lam in (("home", "away", "hg", "lam_h"), ("away", "home", "ag", "lam_a")):
        out.append(pd.DataFrame({"season": p.season, "night": p.gameDate, "goals": p[g], "lam": p[lam],
                                 "own": [z.get((s, t)) for s, t in zip(p.season, p[side])],
                                 "opp": [z.get((s, t)) for s, t in zip(p.season, p[opp])]}))
    d = pd.concat(out, ignore_index=True)
    return d[d.own.notna() & d.opp.notna() & (d.season <= 2025)].reset_index(drop=True)  # finished seasons with speed


def fit(d, w=None):
    """(own, opp) maximizing the Poisson likelihood of goals ~ lam x (1 + own x z_own + opp x z_opp); w = row weights."""
    X = np.c_[d.own.values, d.opp.values]
    y, lam = d.goals.values, d.lam.values
    w = np.ones(len(d)) if w is None else w
    b = np.zeros(2)
    for _ in range(25):  # Newton steps
        f = 1 + X @ b
        grad = X.T @ (w * (y / f - lam))
        hess = -(X * (w * y / f ** 2)[:, None]).T @ X
        step = np.linalg.solve(hess, grad)
        b -= step
        if np.abs(step).max() < 1e-10:
            break
    return b


def deviance(d, b):
    return float(dev(d.goals.values, d.lam.values * (1 + d.own.values * b[0] + d.opp.values * b[1])).mean())


def main():
    games = sm.load_split()
    d = rows(games)
    live = np.array([m.SPEED_OWN, m.SPEED_OPP])
    b = fit(d)
    nights = d.night.unique()
    pos = d.groupby("night").indices
    rs = np.random.default_rng(0)
    boots = []
    for _ in range(1000):
        cnt = np.bincount(rs.integers(0, len(nights), len(nights)), minlength=len(nights))
        w = np.zeros(len(d))
        for k, c in zip(nights, cnt):
            if c:
                w[pos[k]] = c
        boots.append(fit(d, w))
    boots = np.array(boots)
    lo, hi = np.quantile(boots, 0.05, axis=0), np.quantile(boots, 0.95, axis=0)
    net = boots.sum(axis=1)
    print(f"{len(d)} team-games, 2022-23 to 2025-26")
    print(f"live:            own {live[0]:+.4f}  opp {live[1]:+.4f}  net on a total {live.sum():+.4f} per SD")
    print(f"fit 2022-26:     own {b[0]:+.4f} ({lo[0]:+.4f}..{hi[0]:+.4f})  opp {b[1]:+.4f} ({lo[1]:+.4f}..{hi[1]:+.4f})  "
          f"net {b.sum():+.4f} ({np.quantile(net, 0.05):+.4f}..{np.quantile(net, 0.95):+.4f})  [90% ranges, game nights resampled]")
    print("\nfit on each season alone:")
    for s in sorted(d.season.unique()):
        x = fit(d[d.season == s])
        print(f"  {s}-{str(s + 1)[2:]}  own {x[0]:+.4f}  opp {x[1]:+.4f}  net {x.sum():+.4f}  ({(d.season == s).sum()} team-games)")
    print("\nwalk-forward (each season scored with numbers fitted on the seasons before it): team-goal deviance, lower = better")
    print(f"  {'season':8s} {'no speed':>10s} {'live':>10s} {'walk-fwd':>10s}   walk-forward numbers")
    for s in sorted(d.season.unique())[1:]:
        x, test = fit(d[d.season < s]), d[d.season == s]
        print(f"  {s}-{str(s + 1)[2:]:4s} {deviance(test, np.zeros(2)):10.5f} {deviance(test, live):10.5f} {deviance(test, x):10.5f}"
              f"   own {x[0]:+.4f} opp {x[1]:+.4f}")
    later = d[d.season >= 2023]
    print(f"  2023-26  {deviance(later, np.zeros(2)):10.5f} {deviance(later, live):10.5f}")


if __name__ == "__main__":
    main()
