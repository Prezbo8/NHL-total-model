"""League average in the matchup (Nov 2026 audit, finding 1): last season's rate all season (the model before Nov 10
2026, walk_split fixed_lg=True) vs the mean of this season's teams' current ratings (live from Nov 10 2026).

With last season's rate, every projection drifts when league scoring moves (5v5 xG per 60, both teams: 2020-21 4.54,
2021-22 5.00, 2022-23 5.29, 2023-24 5.04, 2024-26 ~4.96). Prints, old vs new: the shared scorecard (research/lib/
judge.py), each season's mean projected total vs mean actual goals (overall and by season quarter), the backtest by
season at the open and close, and SLAM / 1U bets and units.

  python3 research/studies/league_avg.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers

from judge import header, row, scorecard  # first: puts src/ on the path

import numpy as np

import dashboard
import history
import split_model as sm


def backtest(p):
    d = history.flagged(p).merge(history.lines()[lambda x: x.gameDate >= 20200801], on=["gameDate", "home", "away"])
    out = []
    for s in sorted(d.season.unique()):
        o, c = history.bet_results(d[d.season == s], "open"), history.bet_results(d[d.season == s], "close")
        calls = np.array([dashboard.call(r, True) for r in c.itertuples()])
        sl = c.prof[np.isin(calls, ["SLAM", "1U"])]
        out.append((f"{s}-{str(s + 1)[2:]}", len(o), o.prof.mean() * 100 if len(o) else np.nan, len(c), c.prof.mean() * 100,
                    len(sl), sl.sum()))
    o, c = history.bet_results(d, "open"), history.bet_results(d, "close")
    out.append(("2021-26", len(o), o.prof.mean() * 100, len(c), c.prof.mean() * 100, None, None))
    return out


def main():
    games = sm.load_split()
    runs = {fixed: sm.walk_split(games, known_starters=False, record_detail=True, fixed_lg=fixed) for fixed in (True, False)}
    names = {True: "old: last season's rate", False: "new: current team ratings"}
    w = 28
    print(header(w))
    base = scorecard(runs[True], games)
    print(row(names[True], base, w))
    print(row(names[False], scorecard(runs[False], games), w, base))
    print("Accuracy columns: lower = better ('*' = better than old).\n")

    print("Mean projected total minus mean actual goals, by season (and by quarter of the season):")
    print(f"{'season':8s} {'games':>6s} {'actual':>7s} | {'old':>6s} {'q1':>6s} {'q2':>6s} {'q3':>6s} {'q4':>6s} | "
          f"{'new':>6s} {'q1':>6s} {'q2':>6s} {'q3':>6s} {'q4':>6s}")
    for s in sorted(runs[True].season.unique()):
        cells = []
        for fixed in (True, False):
            x = runs[fixed][runs[fixed].season == s].sort_values(["gameDate", "gameId"])
            q = np.array_split(np.arange(len(x)), 4)
            cells.append(f"{x.proj.mean() - x.total.mean():+6.3f} " + " ".join(
                f"{x.proj.iloc[i].mean() - x.total.iloc[i].mean():+6.3f}" for i in q))
        x = runs[True][runs[True].season == s]
        print(f"{s}-{str(s + 1)[2:]:4s} {len(x):6d} {x.total.mean():7.3f} | {cells[0]} | {cells[1]}")

    print("\nBacktest (flagged overs at 6 / 6.5): bets and ROI at the open and close; SLAM + 1U at the close")
    print(f"{'':10s} {'season':8s} {'open':>5s} {'ROI':>7s} {'close':>6s} {'ROI':>7s} {'S+1U':>5s} {'units':>7s}")
    for fixed in (True, False):
        for r in backtest(runs[fixed]):
            sl = f"{r[5]:5d} {r[6]:+7.1f}" if r[5] is not None else ""
            print(f"{names[fixed][:10]:10s} {r[0]:8s} {r[1]:5d} {r[2]:+7.1f} {r[3]:6d} {r[4]:+7.1f} {sl}")
        print()


if __name__ == "__main__":
    main()
