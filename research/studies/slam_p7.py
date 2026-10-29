"""SLAM / 1U + a P(7+) floor (Oct 29 2026): only bet a SLAM (or 1U) when P(7+) >= X. X is picked on 2021-23 ONLY (closing
line ROI, at least 60 bets), then judged on 2023-26. P(7+) is never fit on its own season (as combo_search.py: walk-forward
from 2023, leave-one-season-out before). Same flag, goalie AVOID and lines as the daily backtest.

  python3 research/studies/slam_p7.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))

import dashboard
import history as h
from combo_search import games

PICK, JUDGE = (2021, 2022), (2023, 2025)
FLOORS = [round(0.44 + 0.01 * i, 2) for i in range(12)]  # 44% .. 55%


def rec(b):
    if not len(b):
        return "   0"
    dec = b[b.res != 0]
    return f"{len(b):4d} {(dec.res > 0).mean():5.1%} {b.prof.mean():+6.1%} {b.prof.sum():+6.1f}u"


def main():
    d = games()
    d = d[d.season.between(2021, 2025) & (d.both == True)]  # noqa: E712 (NaN = no line, not flagged)
    d["call"] = [dashboard.call(r, True) for r in d.itertuples()]
    d["ev_sum"] = d.away_ev + d.home_ev
    groups = {"SLAM": d.call == "SLAM", "SLAM + 1U": d.call.isin(["SLAM", "1U"]),
              "combined 5v5 > 4.20": (d.call != "AVOID") & (d.ev_sum > 4.20), "all flagged (not AVOID)": d.call != "AVOID"}
    for when in ("close", "open"):
        print(f"\n=== at the {when} line: bets  over%  ROI  units  (pick half 2021-23 | judge half 2023-26) ===")
        for name, mask in groups.items():
            print(f"\n{name}")
            best = None
            for x in [None] + FLOORS:
                sel = d[mask & (d.p7 >= x)] if x else d[mask]
                b = h.bet_results(sel, when)
                pb, jb = b[b.season.between(*PICK)], b[b.season.between(*JUDGE)]
                tag = "no floor" if x is None else f"P(7+) >= {x:.0%}"
                if x and len(pb) >= 60 and (best is None or pb.prof.mean() > best[1]):
                    best = (x, pb.prof.mean())
                print(f"  {tag:16s} {rec(pb)}  |  {rec(jb)}  |  all {rec(b)}")
            print(f"  -> best floor on 2021-23: {best[0]:.0%}" if best else "  -> no floor with 60+ bets")


if __name__ == "__main__":
    main()
