"""Faster early-season handoff (suggestion #4, Oct 16 2026). SLAM/1U went 15-24 in the first ~150 league games of
2021-26, likely last season's ratings carrying over too strongly. Handoff speed = K (games of last season's prior
before this season counts fully) and REGRESS (summer pull to league average). rating_shrink.py (Oct 10) only tried
MORE prior (K 15-30); this tries LESS: K 5-12 and stronger summer pulls, for 5v5 and penalties drawn / taken
(PP / PK ratings held at the live 15 / 0.33 via pp_k / pp_regress, so only the handoff of the rest moves).

Judged on projection accuracy first: team-goal deviance for each team's first 20 games and for the rest of the season,
2021-23 and 2023-26 separately; then SLAM+1U in the first 150 league games of each season (usual-starter guess) and
all season.

  python3 research/studies/early_handoff.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import numpy as np

import dashboard
import history as h
import model as m
import split_model as sm
from pp_shrink import devs, early

GRID = [(15, 0.33)] + [(k, r) for k in (5, 8, 10, 12, 15) for r in (0.33, 0.45, 0.6) if (k, r) != (15, 0.33)]
FIRST = 150  # league games into each season


def main():
    games = sm.load_split()
    lines = h.lines()
    first = {}
    for s, sg in games.sort_values(["gameDate", "gameId"]).groupby("season"):
        first.update({gid: i < FIRST for i, gid in enumerate(sg.gameId)})
    print(f"{'K':>3s} {'REGRESS':>7s} | {'first20 21-23':>13s} {'first20 23-26':>13s} | {'rest 21-23':>10s} {'rest 23-26':>10s} | "
          f"{'SLAM+1U first 150':>20s} | {'SLAM+1U all, close':>20s}")
    ef = None
    for k, reg in GRID:
        p = sm.walk_split(games, k=k, regress=reg, known_starters=False, record_detail=True, pp_k=m.K, pp_regress=m.REGRESS)
        ef = ef or early(p, games)
        late = {g: not v for g, v in ef.items()}
        d = h.flagged(p).merge(lines, on=["gameDate", "home", "away"])
        d = d[(d.season >= 2021) & d.both]
        c = np.array([dashboard.call(r, True) for r in d.itertuples()])
        b = h.bet_results(d[np.isin(c, ["SLAM", "1U"])], "close")
        bf = b[b.gameId.map(first)] if "gameId" in b else b.iloc[0:0]
        dec = bf[bf.res != 0]
        tag = "  <- live" if (k, reg) == (15, 0.33) else ""
        print(f"{k:3d} {reg:7.2f} | {devs(p, games, (2021, 2022), ef):13.5f} {devs(p, games, (2023, 2025), ef):13.5f} | "
              f"{devs(p, games, (2021, 2022), late):10.5f} {devs(p, games, (2023, 2025), late):10.5f} | "
              f"{int((dec.res > 0).sum()):3d}-{int((dec.res < 0).sum()):3d} {bf.prof.sum():+6.1f}u | {len(b):4d} {b.prof.sum():+6.1f}u{tag}")


if __name__ == "__main__":
    main()
