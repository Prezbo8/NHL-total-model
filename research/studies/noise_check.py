"""Recent adoptions re-judged with error bars (research/lib/judge.py noise(), Nov 2026): is each one's gain beyond noise?
  power-play / penalty-kill K 25 (adopted Oct 16 2026, pp_shrink.py) vs 15 before
  first season's starting averages from both teams (adopted Nov 10 2026, arizona_first.py) vs home only before
A '~' means the difference is within noise (the middle 90% of 500 resamples of game nights includes 0). Nothing is
undone for being noise; only something clearly worse ('x') would be worth a second look.

  python3 research/studies/noise_check.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers

from judge import ci_row, header, noise, row, scorecard  # first: puts src/ on the path

import split_model as sm

CHECKS = {"PP / PK K = 25 (live) vs 15": {"pp_k": 15}, "first season both teams (live) vs home only": {"first_both": False}}


def main():
    games = sm.load_split()
    live = sm.walk_split(games, known_starters=False, record_detail=True)
    sc_live = scorecard(live, games)
    w = 44
    print(header(w))
    print(row("live", sc_live, w))
    for label, old in CHECKS.items():
        before = sm.walk_split(games, known_starters=False, record_detail=True, **old)
        ci = noise(before, live, games)  # live minus the old setting: '*' = the adoption helped beyond noise
        print(row(label, sc_live, w, ci=ci))
        print(row("  (the old setting)", scorecard(before, games), w))
        print(ci_row(ci, w))
    print("\nMarks on the live rows: '*' = the adopted setting is better beyond noise, '~' = within noise, 'x' = worse beyond noise.")


if __name__ == "__main__":
    main()
