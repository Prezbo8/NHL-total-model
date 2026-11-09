"""Arizona -> Utah and the first season's starting averages (Nov 2026 audit, items 1.2, 1.3, 1.4), each alone and together:
  carry_franchise : Utah starts 2024-25 from Arizona's ratings (live: a league-average team, its code is new)
  speed_carry_fix : Arizona's speed moves to Utah only from 2024-25 (live: also for 2022-24, so Arizona's own games
                    in 2022-23 and 2023-24 got no speed)
  first_both      : 2020-21's starting league averages from home AND away teams (live: home only, ~3% high at 5v5, ~7%
                    on the power play)
Prints the shared scorecard (research/lib/judge.py), team-goal deviance in the games each item touches (Utah's first 20
games of 2024-25; Arizona's 2022-24 games; 2020-21 and 2021-22), and the backtest by season.

  python3 research/studies/arizona_first.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers

from judge import header, row, scorecard, team_dev  # first: puts src/ on the path

import numpy as np

import dashboard
import history
import split_model as sm

VARIANTS = {"live": {}, "+ Utah carries Arizona": {"carry_franchise": True}, "+ Arizona speed 2022-24": {"speed_carry_fix": True},
            "+ first season both teams": {"first_both": True},
            "all three": {"carry_franchise": True, "speed_carry_fix": True, "first_both": True}}


def backtest(p):
    d = history.flagged(p).merge(history.lines()[lambda x: x.gameDate >= 20200801], on=["gameDate", "home", "away"])
    out = []
    for s in sorted(d.season.unique()):
        c = history.bet_results(d[d.season == s], "close")
        calls = np.array([dashboard.call(r, True) for r in c.itertuples()])
        out.append(f"{s}-{str(s + 1)[2:]} {len(c):4d} {c.prof.mean() * 100:+6.1f}% S+1U {c.prof[np.isin(calls, ['SLAM', '1U'])].sum():+6.1f}u")
    o, c = history.bet_results(d, "open"), history.bet_results(d, "close")
    out.append(f"2021-26 open {len(o)} {o.prof.mean() * 100:+.1f}%, close {len(c)} {c.prof.mean() * 100:+.1f}%")
    return out


def main():
    games = sm.load_split()
    runs = {k: sm.walk_split(games, known_starters=False, record_detail=True, **v) for k, v in VARIANTS.items()}
    p = runs["live"].sort_values(["gameDate", "gameId"])
    uta = p[(p.season == 2024) & ((p.home == "UTA") | (p.away == "UTA"))].gameId.head(20)
    ari = p[p.season.isin([2022, 2023]) & ((p.home == "ARI") | (p.away == "ARI"))].gameId
    only = lambda ids: dict.fromkeys(ids, True)
    w = 28
    print(header(w) + f" {'UTA 1st 20':>11s} {'ARI 22-24':>11s} {'dev 20-21':>11s}")
    base = scorecard(runs["live"], games)
    for k, x in runs.items():
        extra = (f" {team_dev(x, games, (2024, 2024), only(uta)):11.5f} {team_dev(x, games, (2022, 2023), only(ari)):11.5f}"
                 f" {team_dev(x, games, (2020, 2020)):11.5f}")
        print(row(k, scorecard(x, games), w, None if k == "live" else base) + extra)
    print("Accuracy columns: lower = better ('*' = better than live).\n")
    for k, x in runs.items():
        print(f"{k}:")
        for line in backtest(x):
            print("   " + line)


if __name__ == "__main__":
    main()
