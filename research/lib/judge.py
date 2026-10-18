"""One scorecard for model variants (Oct 18 2026 round), so every study is judged the same way:
accuracy first (team-goal Poisson deviance 2021-23 and 2023-26, the same for each team's first 20 games, log loss of
the over/under lean vs closing and opening lines 2024-26), then bets (all flagged overs ROI, SLAM+1U units, 2021-26,
at the opening and closing line). A variant is only worth adopting if it is better on BOTH halves.

  from judge import scorecard, header, row
"""
import os as _os
import sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_sys.path.insert(0, _os.path.join(_here, "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_here, "..", "studies"))

import numpy as np

import dashboard
import history
import odds
from compare import score

_EARLY = {}


def dev(y, lam):
    return 2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / lam), 0) - (y - lam))


def early(p):
    """{gameId: True} when either team is within its first 20 games of the season (cached per game set)."""
    key = len(p)
    if key not in _EARLY:
        n, flag = {}, {}
        for r in p.sort_values(["gameDate", "gameId"]).itertuples():
            a, b = n.get((r.season, r.home), 0), n.get((r.season, r.away), 0)
            flag[r.gameId] = a < 20 or b < 20
            n[(r.season, r.home)], n[(r.season, r.away)] = a + 1, b + 1
        _EARLY[key] = flag
    return _EARLY[key]


def team_dev(p, games, seasons, only=None):
    x = p.merge(games[["gameId", "hg", "ag"]], on="gameId")
    x = x[x.season.between(*seasons)]
    if only is not None:
        x = x[x.gameId.map(only).fillna(False).astype(bool)]
    return float(np.concatenate([dev(x.hg, x.lam_h), dev(x.ag, x.lam_a)]).mean())


def scorecard(p, games):
    """p = split_model.walk_split(..., record_detail=True) output."""
    ef = early(p)
    out = {"dev 21-23": team_dev(p, games, (2021, 2022)), "dev 23-26": team_dev(p, games, (2023, 2025)),
           "early 21-23": team_dev(p, games, (2021, 2022), ef), "early 23-26": team_dev(p, games, (2023, 2025), ef),
           "LL close": score(p, odds.ODDS)[1], "LL open": score(p, odds.ODDS_OPEN)[1]}
    d = history.flagged(p).merge(history.lines()[lambda x: x.gameDate >= 20200801], on=["gameDate", "home", "away"])
    for when in ("open", "close"):
        b = history.bet_results(d, when)
        out[f"ROI {when}"] = b.prof.mean() * 100
        b = b[b.season >= 2021]
        calls = np.array([dashboard.call(r, True) for r in b.itertuples()])
        out[f"S+1U {when}"] = float(b.prof[np.isin(calls, ["SLAM", "1U"])].sum())
    return out


COLS = [("dev 21-23", "{:.5f}"), ("dev 23-26", "{:.5f}"), ("early 21-23", "{:.5f}"), ("early 23-26", "{:.5f}"),
        ("LL close", "{:.4f}"), ("LL open", "{:.4f}"), ("ROI open", "{:+.1f}%"), ("ROI close", "{:+.1f}%"),
        ("S+1U open", "{:+.1f}u"), ("S+1U close", "{:+.1f}u")]


def header(width=30):
    return f"{'variant':{width}s} " + " ".join(f"{c:>11s}" for c, _ in COLS)


def row(label, sc, width=30, base=None):
    """One printed line; with base, accuracy columns get a '*' when better than base (lower)."""
    cells = []
    for c, f in COLS:
        s = f.format(sc[c])
        if base is not None and c.startswith(("dev", "early", "LL")):
            s += "*" if sc[c] < base[c] - 1e-6 else " "
        cells.append(f"{s:>11s}")
    return f"{label:{width}s} " + " ".join(cells)
