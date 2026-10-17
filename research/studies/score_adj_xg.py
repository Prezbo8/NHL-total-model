"""Score-adjusted xG in the 5v5 / power-play team ratings (suggestion #1, Oct 16 2026).
The ratings use raw MoneyPuck xGoals. Teams protecting a lead give up more shots (and take fewer), trailing teams the
opposite, so raw xG makes frequent leaders look worse and chasers better. MoneyPuck also publishes score-and-venue-adjusted
xG, flurry-adjusted xG (rebound flurries counted once) and both. Only the situation xG in the ratings changes; the
game-level xG behind goalie GSAx stays raw, so goalies are identical across variants.

Judged on projection accuracy first: team-goal deviance (lower = better) 2021-23 and 2023-26 separately, log loss
of the over/under lean vs closing and opening lines 2024-26; then the flag-rule bets (open / close, 2021-26).

  python3 research/studies/score_adj_xg.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import odds
import split_model as sm
from compare import score
from injury_backtest import team_dev
from recency_ratings import bets

VARIANTS = (("raw (live)", "xGoals"), ("score+venue", "scoreVenueAdjustedxGoals"),
            ("flurry", "flurryAdjustedxGoals"), ("flurry+score+venue", "flurryScoreVenueAdjustedxGoals"))


def games_with(xg, base, rescale=False):
    """base (raw xG everywhere) with the situation xG columns swapped for the `xg` version. rescale: each season and
    situation scaled to raw xG's league total (only who looks better / worse changes, not the league level)."""
    if xg == "xGoals":
        return base
    alt = sm.load_split(xg=xg).set_index("gameId")
    g = base.copy()
    cols = [c for c in g.columns if c.endswith(("_xFor", "_xAgainst"))]
    g[cols] = alt.loc[g.gameId, cols].values
    if rescale:
        for c in cols:
            g[c] *= g.season.map(base.groupby("season")[c].sum() / g.groupby("season")[c].sum())
    return g


def main():
    base = sm.load_split()
    print(f"{'5v5/PP xG':31s} {'team dev 21-23':>14s} {'team dev 23-26':>14s} {'LL close':>9s} {'LL open':>8s}"
          f"   {'bets open':>11s}   {'bets close':>11s}   league xG/goals 5v5")
    for (name, xg), rescale in [(v, False) for v in VARIANTS] + [(v, True) for v in VARIANTS[1:]]:
        g = games_with(xg, base, rescale)
        name += " (rescaled)" if rescale else ""
        p = sm.walk_split(g, known_starters=False)
        bo, bc = bets(p)
        ratio = g.ev_xFor.sum() / g.ev_goalsFor.sum() if "ev_goalsFor" in g else float("nan")
        print(f"{name:31s} {team_dev(p, g, (2021, 2022)):14.4f} {team_dev(p, g, (2023, 2025)):14.4f} "
              f"{score(p, odds.ODDS)[1]:9.4f} {score(p, odds.ODDS_OPEN)[1]:8.4f}   {bo}   {bc}   {ratio:.3f}")


if __name__ == "__main__":
    main()
