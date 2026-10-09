"""Grade model variants against real lines on the unseen test seasons (2024-25, 2025-26).

  python3 research/studies/compare.py           # vs closing lines
  python3 research/studies/compare.py open      # vs opening lines
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))  # model code lives in src/
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
import os
import sys

import numpy as np

import grade
import model as m
import odds
import split_model as sm

VARIANTS = {
    "current model":                    lambda ks: m.walk(m.load_games(), known_starters=ks)[0],
    "no goalies, no b2b (original)":    lambda ks: m.walk(m.load_games(), use_goalies=False, use_b2b=False)[0],
    "score/venue/flurry-adjusted xG":   lambda ks: m.walk(m.load_games(xg="flurryScoreVenueAdjustedxGoals"), known_starters=ks)[0],
    "recent games weighted (0.97)":     lambda ks: m.walk(m.load_games(), recency=0.97, known_starters=ks)[0],
    "player-based start (50%)":         lambda ks: m.walk(m.load_games(), roster_w=0.5, known_starters=ks)[0],
    "5v5 / power play split":           lambda ks: sm.walk_split(sm.load_split(), known_starters=ks),
}


def score(proj, path):
    cal = m.fit_calibration(proj[proj.season.between(2022, 2023)])
    d = grade.with_lines(proj[proj.season >= 2024], cal, path)
    te = d[d.result != 0]
    y = (te.result == 1).values.astype(float)
    ll = lambda p: -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    out = [len(d), ll(te.m_over_np.values), ll(te.mkt_over.values)]
    for edge in (0.0, 0.04):
        _, prof, won = grade.bets(d, edge)
        out += [len(prof), won[prof.values != 0].mean(), prof.mean()]
    return out


def main():
    opening = "open" in sys.argv
    path = odds.ODDS_OPEN if opening else odds.ODDS
    if not os.path.exists(path):
        sys.exit(f"{path} not downloaded yet")
    modes = [False, True] if opening else [True]
    print(f"vs {'OPENING' if opening else 'CLOSING'} lines, 2024-25 + 2025-26")
    print(f"{'variant':34s} {'starters':9s} {'games':>5s} {'model LL':>9s} {'mkt LL':>7s}"
          f"   all leans: n / win / ROI        edge>=4%: n / win / ROI")
    for name, fn in VARIANTS.items():
        for ks in modes:
            n, llm, llk, n0, w0, r0, n4, w4, r4 = score(fn(ks), path)
            print(f"{name:34s} {'known' if ks else 'guessed':9s} {n:5d} {llm:9.4f} {llk:7.4f}"
                  f"   {n0:4d} / {w0:.1%} / {r0:+.1%}      {n4:4d} / {w4:.1%} / {r4:+.1%}")


if __name__ == "__main__":
    main()
