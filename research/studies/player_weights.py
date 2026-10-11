"""Player ratings behind the injury/lineup adjustment: season weights (1.0 / 0.7 / 0.4), stat mix (50% advanced,
50% regular) and shrink toward replacement (400 minutes) were set up front. Test each, one at a time, on who
actually dressed 2021-26 (players rated only from seasons before the game's), with injuries at the live 1.15x.

Judged on team-goal accuracy (all games and games where injuries moved a team 3%+, Poisson log loss, lower =
better) and the slope of goals-vs-model on the adjustment (1.0 = right size).

  python3 research/studies/player_weights.py      # needs data/dressed.csv (research/lib/lineups_hist.py)
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from functools import partial
from math import lgamma

import numpy as np
import pandas as pd

import injuries
import injury_backtest as ib
import paths
import players
import split_model as sm

LIVE_TABLE = players.player_table
ADV_OFF, ADV_DEF = {"OnIce_F_xGoals": 1.0}, {"OnIce_A_xGoals": 1.0}
REG_OFF = {"OnIce_F_xGoals": 0.25, "OnIce_F_goals": 0.25, "I_F_goals": 0.25, "I_F_points": 0.25}
REG_DEF = {"OnIce_A_xGoals": 0.25, "OnIce_A_shotsOnGoal": 0.75}
VARIANTS = [
    ("current (1.0/0.7/0.4, 50-50, 400 min)", {}),
    ("seasons 1.0 / 0.5 / 0.25", {"season_w": (1.0, 0.5, 0.25)}),
    ("seasons 1.0 / 0.85 / 0.7 (flatter)", {"season_w": (1.0, 0.85, 0.7)}),
    ("seasons 1.0 / 0.4 / 0.1 (recent-heavy)", {"season_w": (1.0, 0.4, 0.1)}),
    ("last season only", {"season_w": (1.0,)}),
    ("stats: advanced only (on-ice xG)", {"offense": ADV_OFF, "defense": ADV_DEF}),
    ("stats: 25% advanced / 75% regular", {"offense": REG_OFF, "defense": REG_DEF}),
    ("shrink 200 minutes", {"shrink_min": 200}),
    ("shrink 800 minutes", {"shrink_min": 800}),
]


def main():
    g = sm.load_split()
    dressed = pd.read_csv(paths.data("dressed.csv"))
    base = sm.walk_split(g, known_starters=True)
    x0 = base.merge(g[["gameId", "hg", "ag"]], on="gameId")
    lp = lambda k_, lam: k_ * np.log(lam) - lam - np.array([lgamma(v + 1) for v in k_])
    print(f"{'player ratings':42s} {'LL all 21-26':>12s} {'LL 23-26':>9s} {'LL big-injury':>13s} {'(games)':>7s} {'slope':>6s}")
    for name, kw in VARIANTS:
        players.player_table = partial(LIVE_TABLE, **kw)
        eff = ib.missing_effects(g, dressed)
        players.player_table = LIVE_TABLE
        p = ib.adjusted(base, eff, injuries.SCALE).merge(g[["gameId", "hg", "ag"]], on="gameId")
        move = np.maximum(np.abs(p.lam_h / x0.lam_h - 1), np.abs(p.lam_a / x0.lam_a - 1))
        ll = lambda t: -np.mean(np.r_[lp(t.hg.values, t.lam_h.values), lp(t.ag.values, t.lam_a.values)])
        a = p[p.season.between(2021, 2025)]
        big = a[(move[a.index] >= 0.03).values]
        # slope of (goals / no-injury projection - 1) on the adjustment, team level
        rows = []
        for r0, r1 in zip(x0[x0.season.between(2021, 2025)].itertuples(), a.itertuples()):
            rows += [(r0.hg / r0.lam_h - 1, r1.lam_h / r0.lam_h - 1), (r0.ag / r0.lam_a - 1, r1.lam_a / r0.lam_a - 1)]
        t = np.array(rows)
        slope = np.polyfit(t[:, 1], t[:, 0], 1)[0] if t[:, 1].std() > 0 else float("nan")
        print(f"{name:42s} {ll(a):12.5f} {ll(a[a.season >= 2023]):9.5f} {ll(big):13.5f} {len(big):7d} {slope:6.2f}")


if __name__ == "__main__":
    main()
