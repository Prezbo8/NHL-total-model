"""Weights for the Total Offense / Total Defense rankings (dashboard Team rankings tab).

Each stat's weight = how well it predicts a team's FUTURE goals: for every team-season 2021-22 to 2025-26,
the stat over one half of the season vs goals per game in the other half (both directions), Pearson r.
Weight = r squared (share of future scoring it explains on its own), normalised to sum to 1.
Defense mirrors it with the same stats allowed and future goals allowed.

  python3 research/studies/offense_weights.py
"""
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "lib"))  # shared research helpers
import pandas as pd

from split_model import KEYS, team_games


def weights(tg):
    rows = []
    for (s, t), x in tg.groupby(["season", "team"]):
        if len(x) < 60:
            continue
        h1, h2 = x.iloc[: len(x) // 2], x.iloc[len(x) // 2:]
        for a, b in ((h1, h2), (h2, h1)):
            rows.append({**{f"{k}{side}": a[f"{k}{side}"].mean() for k in KEYS for side in "FA"},
                         "futF": b.goalsF.mean(), "futA": b.goalsA.mean()})
    r = pd.DataFrame(rows)
    out = {}
    for side, fut in (("F", "futF"), ("A", "futA")):
        corr = {k: r[f"{k}{side}"].corr(r[fut]) for k in KEYS}
        w = {k: max(c, 0) ** 2 for k, c in corr.items()}
        tot = sum(w.values())
        out[side] = {k: (round(w[k] / tot, 3), round(corr[k], 3)) for k in KEYS}
    return out, len(r)


if __name__ == "__main__":
    w, n = weights(team_games())
    print(f"{n} half-season samples (2021-22 to 2025-26)")
    for side, name in (("F", "OFFENSE (stats for -> future goals for)"), ("A", "DEFENSE (stats allowed -> future goals allowed)")):
        print(f"\n{name}")
        for k, (wt, c) in sorted(w[side].items(), key=lambda kv: -kv[1][0]):
            print(f"  {k:6s} r={c:+.3f}  weight {wt:.3f}")
