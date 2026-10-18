"""Rink scorer bias in xG (suggestion #3, Oct 18 2026). Shot locations are recorded by each arena's scorers, and some
rinks record shots closer (more xG) or farther than others; hits had exactly this problem (hits.py). Rink factor for an
arena = xG per 60 (both teams, every situation the ratings use) in the home team's home games / the same in its road
games, divided by the league's typical ratio so real home-ice effects cancel. Factors come from EARLIER seasons only
(last season, or the last two pooled), shrunk toward 1 by `strength`. Every xG number recorded in that arena is divided
by its factor before it goes into the 5v5 / power-play ratings. Goalie ratings are unchanged (their own xG file).

  1. Does a rink's factor repeat the next season? (correlation, all arenas)
  2. Scorecard: live vs rink-corrected ratings.

  python3 research/studies/rink_bias.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import header, row, scorecard  # first: puts src/ on the path
import numpy as np
import pandas as pd

import split_model as sm

XCOLS = ["ev_xFor", "ev_xAgainst", "pp_xFor", "pp_xAgainst", "pk_xFor", "pk_xAgainst"]


def raw_factors(games):
    """{(season, team): home xG rate / road xG rate, divided by that season's league median}."""
    g = games.assign(x=games[["ev_xFor", "ev_xAgainst", "pp_xFor", "pp_xAgainst", "pk_xFor", "pk_xAgainst"]].sum(axis=1),
                     t=games[["ev_iceTime", "pp_iceTime", "pk_iceTime"]].sum(axis=1))
    out = {}
    for s, sg in g.groupby("season"):
        home = sg.groupby("home")[["x", "t"]].sum()
        road = sg.groupby("away")[["x", "t"]].sum()
        ratio = (home.x / home.t) / (road.x / road.t)
        ratio = ratio / ratio.median()
        out.update({(s, t): v for t, v in ratio.items()})
    return out


def corrected(games, raw, seasons_back=1, strength=1.0):
    g = games.copy()
    f = []
    for s, t in zip(g.season, g.home):
        vals = [raw[(s - k, t)] for k in range(1, seasons_back + 1) if (s - k, t) in raw]
        f.append(1 + strength * (np.mean(vals) - 1) if vals else 1.0)
    f = np.array(f)
    for c in XCOLS:
        g[c] = g[c] / f
    return g


def main():
    games = sm.load_split()
    raw = raw_factors(games)
    pairs = [(v, raw[(s + 1, t)]) for (s, t), v in raw.items() if (s + 1, t) in raw]
    a, b = np.array(pairs).T
    print(f"1. rink factor, one season vs the next: r = {np.corrcoef(a, b)[0, 1]:.2f} ({len(pairs)} arena-pairs); "
          f"spread (sd) {a.std():.3f}")
    last = pd.Series({t: v for (s, t), v in raw.items() if s == games.season.max()}).sort_values()
    print(f"   latest season, lowest: {', '.join(f'{t} {v:.2f}' for t, v in last.head(3).items())}; "
          f"highest: {', '.join(f'{t} {v:.2f}' for t, v in last.tail(3).items())}\n")
    print("2. " + header(30))
    base = None
    for back, strength in [(0, 0.0), (1, 0.5), (1, 1.0), (2, 0.5), (2, 1.0)]:
        g = games if back == 0 else corrected(games, raw, back, strength)
        p = sm.walk_split(g, known_starters=False, record_detail=True)
        sc = scorecard(p, games)  # judged on the real goals
        base = base or sc
        print("   " + row("live (raw xG)" if back == 0 else f"last {back} season(s), strength {strength}", sc, 30, base))


if __name__ == "__main__":
    main()
