"""Goalie shrink 150 vs 200 (live G_SHRINK), rechecked Nov 5 2026 with 2026-27 games so far. goalie_retune.py
(Oct 2026) found 150 "slightly better on bets" and parked it for a recheck.

Judged on the shared scorecard (research/lib/judge.py: team-goal deviance 2021-23 and 2023-26, the same for each team's
first 20 games, log loss vs closing / opening lines, flagged-over ROI and SLAM+1U units at the open and close), plus
team-goal deviance for 2026-27 so far. Rows with the backtest's usual-starter guess (as every study) and with the real
starter (what the last pre-game run has). Shrink 150 spreads goalie ratings wider, so it's judged twice: with today's
Gl tag cutoffs (more goalies would be Strong / Good, so more AVOIDs), and with the cutoffs re-fitted the way the live
ones were made (2024-26 team-game quintiles: each tag keeps 20% of games). Accuracy doesn't depend on the cutoffs.

  python3 research/studies/goalie_shrink.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers

from judge import header, row, scorecard, team_dev  # first: puts src/ on the path

import numpy as np

import dashboard
import model as m
import split_model as sm

LIVE_CUTS = dashboard.TIERS["gadj"]


def walk(games, shrink, known):
    m.GoalieSkill.__init__.__defaults__ = (shrink, m.G_DECAY)
    try:
        return sm.walk_split(games, known_starters=known, record_detail=True)
    finally:
        m.GoalieSkill.__init__.__defaults__ = (m.G_SHRINK, m.G_DECAY)


def quintiles(p):
    """Gl tag cutoffs as the live ones were made: quintiles of every 2024-26 team-game's goalie adjustment."""
    x = p[p.season.isin((2024, 2025))]
    return tuple(round(float(q), 3) for q in np.quantile(np.r_[x.home_gadj.values, x.away_gadj.values], (0.2, 0.4, 0.6, 0.8)))


def card(p, games, cuts):
    dashboard.TIERS["gadj"] = cuts
    try:
        return scorecard(p, games)
    finally:
        dashboard.TIERS["gadj"] = LIVE_CUTS


def main():
    games = sm.load_split()
    runs = {(s, known): walk(games, s, known) for s in (200, 150) for known in (False, True)}
    q200, q150 = quintiles(runs[(200, False)]), quintiles(runs[(150, False)])
    print(f"Gl tag cutoffs: live {LIVE_CUTS} | re-made with shrink 200 {q200} | with shrink 150 {q150}")
    sd = {s: float(np.std(np.r_[runs[(s, False)].home_gadj, runs[(s, False)].away_gadj])) for s in (200, 150)}
    print(f"Spread of goalie adjustments (sd, all team-games): shrink 200 {sd[200]:.4f}, shrink 150 {sd[150]:.4f}\n")
    w = 34
    print(header(w) + f" {'dev 26-27':>11s}")
    for known, label in ((False, "usual-starter guess"), (True, "real starter")):
        base = card(runs[(200, known)], games, LIVE_CUTS)
        print(row(f"200 (live), {label}", base, w) + f" {team_dev(runs[(200, known)], games, (2026, 2026)):11.5f}")
        for cuts, tag in ((LIVE_CUTS, "same cutoffs"), (q150, "re-fit cutoffs")):
            sc = card(runs[(150, known)], games, cuts)
            print(row(f"150, {label}, {tag}", sc, w, base) + f" {team_dev(runs[(150, known)], games, (2026, 2026)):11.5f}")
        print()
    print("Accuracy columns: lower = better ('*' = better than 200 on the same starters). Adopt only if better on BOTH halves.")


if __name__ == "__main__":
    main()
