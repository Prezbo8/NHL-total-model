"""New goalies (Oct 22 2026, after Cooper Black's debut was rated exactly average). Live: a goalie's skill = goals saved
above expected / (xG faced + 200), so a goalie with no NHL record is rated average (0%). Here a goalie early in his NHL
career starts from a below-average prior instead: skill = (GSAx - 200 x c x fade) / (xG + 200), fade = 1 - n / N
for his n-th NHL appearance (career, counted from 2008-09; 0 after N). c = how much worse than average a debut goalie is.

(1) Raw: goals / xG by career start number, 2021-26 (starts only).
(2) Grid c x N, judged on team-goal deviance with the REAL starter (both halves + games where a new goalie starts) and on
    judge.scorecard (the daily backtest's usual-starter guess, bets).

  python3 research/studies/new_goalie.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import dev, header, row, scorecard  # first: puts src/ on the path
import numpy as np
import pandas as pd

import model as m
import split_model as sm

LIVE_INIT, LIVE_ADD, LIVE_SKILL = m.GoalieSkill.__init__, m.GoalieSkill.add, m.GoalieSkill.skill
SEED = {}  # NHL appearances before the model's data starts (2008-09 to 2019-20)


def patch(c, n_full):
    def init(self, history, shrink=m.G_SHRINK, decay=m.G_DECAY):
        self.n = dict(SEED)
        LIVE_INIT(self, history, shrink, decay)

    def add(self, p, xg, g):
        self.n[p] = self.n.get(p, 0) + 1
        LIVE_ADD(self, p, xg, g)

    def skill(self, p):
        xg, gsax = self.c.get(p, (0.0, 0.0))
        fade = max(0.0, 1 - self.n.get(p, 0) / n_full)
        return (gsax - self.shrink * c * fade) / (xg + self.shrink)
    m.GoalieSkill.__init__, m.GoalieSkill.add, m.GoalieSkill.skill = init, add, skill


def unpatch():
    m.GoalieSkill.__init__, m.GoalieSkill.add, m.GoalieSkill.skill = LIVE_INIT, LIVE_ADD, LIVE_SKILL


def main():
    starter, _, gg = m.load_goalies()
    gg = gg.sort_values("gameId")
    SEED.update(gg[gg.gameDate < 20200801].groupby("playerId").size().to_dict())
    gg["n_before"] = gg.groupby("playerId").cumcount()  # career appearances before this game
    nb = {(g, p): n for g, p, n in zip(gg.gameId, gg.playerId, gg.n_before)}
    # facing a starter with fewer than 20 career appearances: (gameId, side whose GOALS he faces)
    games = sm.load_split()
    new_for = {}
    for r in games.itertuples():
        for side, opp in (("h", r.away), ("a", r.home)):
            p = starter.get((r.gameId, opp))
            new_for[(r.gameId, side)] = p is not None and nb.get((r.gameId, p), 99) < 20

    print("(1) goals / xG by career start number, starts 2021-26 (all starters 2021-26 = baseline)")
    st = gg.merge(pd.DataFrame([(g, p) for (g, t), p in starter.items()], columns=["gameId", "playerId"]), on=["gameId", "playerId"])
    st = st[st.gameDate >= 20210801]
    base = st.goals.sum() / st.xGoals.sum()
    for lo, hi in ((0, 0), (1, 4), (5, 9), (10, 19), (20, 39), (40, 10 ** 6)):
        y = st[st.n_before.between(lo, hi)]
        r = y.goals.sum() / y.xGoals.sum()
        se = (y.goals - y.xGoals * r).std() * np.sqrt(len(y)) / y.xGoals.sum()
        print(f"  appearance {lo + 1}-{hi + 1 if hi < 10 ** 6 else 'on'}: {len(y):5d} starts  {r / base - 1:+6.1%} ±{2 * se / base:.1%}")

    def real_dev(p):
        x = p.merge(games[["gameId", "hg", "ag"]], on="gameId")
        out = []
        for seasons in ((2021, 2022), (2023, 2025)):
            y = x[x.season.between(*seasons)]
            out.append(np.concatenate([dev(y.hg, y.lam_h), dev(y.ag, y.lam_a)]).mean())
        y = x[x.season >= 2021]
        mh = np.array([new_for[(g, "h")] for g in y.gameId]); ma = np.array([new_for[(g, "a")] for g in y.gameId])
        dn = np.concatenate([dev(y.hg[mh], y.lam_h[mh]), dev(y.ag[ma], y.lam_a[ma])])
        bias = np.concatenate([(y.hg - y.lam_h)[mh], (y.ag - y.lam_a)[ma]])
        out += [dn.mean(), bias.mean(), len(dn)]
        return out

    print("\n(2) real starter: team-goal deviance 21-23 / 23-26 / goals facing a new goalie (<20 apps): deviance, actual - proj")
    rows = []
    for c, n_full in [(0.0, 20)] + [(c, n) for c in (0.02, 0.04, 0.06, 0.08) for n in (10, 20, 40)]:
        patch(c, n_full) if c else unpatch()
        rd = real_dev(sm.walk_split(games, known_starters=True))
        sc = scorecard(sm.walk_split(games, known_starters=False, record_detail=True), games)
        rows.append((c, n_full, rd, sc))
    unpatch()
    b = rows[0][2]
    for c, n_full, rd, _ in rows:
        mark = lambda i: "*" if rd[i] < b[i] - 1e-6 else " "
        print(f"  {'live (average)' if not c else f'c {c:.0%}, fade over {n_full}':24s} {rd[0]:.5f}{mark(0)} {rd[1]:.5f}{mark(1)}"
              f"   new-goalie games {rd[4]}: {rd[2]:.5f}{mark(2)} bias {rd[3]:+.3f}")
    print("\n" + header(26))
    for c, n_full, _, sc in rows:
        print(row("live (average)" if not c else f"c {c:.0%}, fade over {n_full}", sc, 26, rows[0][3]))


if __name__ == "__main__":
    main()
