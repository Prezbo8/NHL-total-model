"""Goals vs xG mix, offense and defense separately (suggestion #2, Oct 18 2026). Live: offense (5v5 and power play)
= 50% actual goals + 50% xG (m.W_GOALS); defense (5v5 and penalty kill) = xG only, because goals allowed vs xG is
mostly goaltending and the goalie rating already counts it. Finishing skill may be more real than "allowing fewer goals
than xG", so the best mix can differ by side. Grid: offense share of goals w, defense share w_def
(split_model.walk_split w / w_def).

  python3 research/studies/goals_xg_mix.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))

from judge import header, row, scorecard  # first: puts src/ on the path
import split_model as sm


def main():
    games = sm.load_split()
    base = None
    print(header(30))
    grid = [(0.5, 0.0)] + [(w, wd) for w in (0.3, 0.4, 0.5, 0.6, 0.7) for wd in (0.0, 0.15, 0.3) if (w, wd) != (0.5, 0.0)]
    for w, wd in grid:
        p = sm.walk_split(games, known_starters=False, record_detail=True, w=w, w_def=wd)
        sc = scorecard(p, games)
        base = base or sc
        print(row("live: off 50%, def 0%" if (w, wd) == (0.5, 0.0) else f"off {w:.0%} goals, def {wd:.0%}", sc, 30, base))


if __name__ == "__main__":
    main()
