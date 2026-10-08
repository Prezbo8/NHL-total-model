"""P(7+) calibration, 2023-26 backtest: games grouped by predicted P(7+), predicted vs how often they went 7+.
P(7+) is walk-forward (fit only on earlier seasons, 2022..s-1), as the daily run does. Prints the bins pasted
into dashboard.CALIBRATION_BACKTEST.

  python3 research/p7_calibration.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "src"))
import pandas as pd

import dashboard
import model as m
import split_model as sm


def main():
    p = sm.walk_split(sm.load_split(), known_starters=False)
    rows = []
    for s in range(2023, 2026):
        cal = m.fit_calibration(p[p.season.between(2022, s - 1)])
        x = p[p.season == s].copy()
        x["p7"] = m.p_from(cal, 7, x.proj.values)
        rows.append(x)
    d = pd.concat(rows)
    out = dashboard.calibration_bins(d.p7, d.total >= 7)
    print(f"{len(d)} games")
    print("CALIBRATION_BACKTEST = [  # (bin label, games, mean predicted P(7+), share that went 7+): research/p7_calibration.py")
    for b in out:
        print(f"    ({b[0]!r}, {b[1]}, {b[2]:.4f}, {b[3]:.4f}),")
    print("]")


if __name__ == "__main__":
    main()
