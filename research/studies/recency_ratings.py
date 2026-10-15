"""Recency weighting INSIDE the live 5v5 / power-play team ratings (follow-up to recent_form.py, where last-days xG
form still carried over ~6-9%). Each time a team's rating takes in a game, its earlier totals are first multiplied
by d (d = 1.0: every game counts the same = live; 0.98: a game 35 games ago counts half). Applies to every rating
part (5v5 offense / defense, power play, penalty kill, penalties drawn / taken); the season-end carry-over is built
from the faded totals too. compare.py tested this only on the old one-number model (0.97, lost).

Judged on projection accuracy first: team-goal deviance (lower = better) 2021-23 and 2023-26 separately, log loss
of the over/under lean vs closing and opening lines 2024-26; then the flag-rule bets (open / close, 2021-26).

  python3 research/studies/recency_ratings.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import history
import odds
import split_model as sm
from compare import score
from injury_backtest import team_dev

DECAYS = (1.0, 0.995, 0.99, 0.98, 0.97, 0.95)
LIVE_ADD = sm.Rate.add


def faded_add(d):
    def add(self, t, num, den):
        n, dnm = self.sum.get(t, (0.0, 0.0))
        self.sum[t] = (d * n + num, d * dnm + den)
    return add


def bets(p):
    d = history.flagged(p).merge(history.lines()[lambda x: x.gameDate >= 20200801], on=["gameDate", "home", "away"])
    out = []
    for when in ("open", "close"):
        b = history.bet_results(d, when)
        out.append(f"{len(b):4d} {b.prof.mean():+6.1%}")
    return out


def main():
    games = sm.load_split()
    print(f"{'fade per game':16s} {'team dev 21-23':>14s} {'team dev 23-26':>14s} {'LL close':>9s} {'LL open':>8s}"
          f"   {'bets open':>11s}   {'bets close':>11s}")
    for d in DECAYS:
        sm.Rate.add = LIVE_ADD if d == 1.0 else faded_add(d)
        p = sm.walk_split(games, known_starters=False)
        name = "1.0 (live)" if d == 1.0 else f"{d} (half {0.693 / (1 - d):.0f} g)"
        bo, bc = bets(p)
        print(f"{name:16s} {team_dev(p, games, (2021, 2022)):14.4f} {team_dev(p, games, (2023, 2025)):14.4f} "
              f"{score(p, odds.ODDS)[1]:9.4f} {score(p, odds.ODDS_OPEN)[1]:8.4f}   {bo}   {bc}")
    sm.Rate.add = LIVE_ADD


if __name__ == "__main__":
    main()
