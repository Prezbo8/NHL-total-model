"""One scorecard for model variants (Oct 18 2026 round), so every study is judged the same way:
accuracy first (team-goal Poisson deviance 2021-23 and 2023-26, the same for each team's first 20 games, log loss of
the over/under lean vs closing and opening lines 2024-26), then bets (all flagged overs ROI, SLAM+1U units, 2021-26,
at the opening and closing line). A variant is only worth adopting if it is better on BOTH halves.

  from judge import scorecard, header, row, noise

noise(live_p, variant_p, games) adds error bars (Nov 2026): a bootstrap over game NIGHTS (games on one night share
conditions) of 'variant minus live' for every column; row(..., ci=noise(...)) marks each difference '*' (better beyond
noise), '~' (within noise: the middle 90% of the resampled differences includes 0) or 'x' (worse beyond noise).
"""
import os as _os
import sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_sys.path.insert(0, _os.path.join(_here, "..", "..", "src"))
_sys.path.insert(0, _os.path.join(_here, "..", "studies"))

import numpy as np
import pandas as pd

import dashboard
import grade
import history
import model as m
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


def per_game(p, games):
    """One row per game with what each scorecard column adds up from: team-goal deviance (both teams), the early-season
    flag, the over/under log loss vs the closing and opening lines (2024-26, calibrated on 2022-23, as compare.score), and
    the flagged-over profit at the open / close with the SLAM + 1U part (as scorecard)."""
    x = p.merge(games[["gameId", "hg", "ag"]], on="gameId")
    ef = early(p)
    out = pd.DataFrame({"gameId": x.gameId, "gameDate": x.gameDate, "season": x.season,
                        "dev": dev(x.hg, x.lam_h) + dev(x.ag, x.lam_a), "early": x.gameId.map(ef).fillna(False).astype(bool)})
    cal = m.fit_calibration(p[p.season.between(2022, 2023)])
    for col, path in (("LL close", odds.ODDS), ("LL open", odds.ODDS_OPEN)):
        d = grade.with_lines(p[p.season >= 2024], cal, path)
        d = d[d.result != 0]
        y, q = (d.result == 1).values.astype(float), d.m_over_np.values
        out = out.merge(pd.DataFrame({"gameId": d.gameId, col: -(y * np.log(q) + (1 - y) * np.log(1 - q))}), on="gameId", how="left")
    d = history.flagged(p).merge(history.lines()[lambda z: z.gameDate >= 20200801], on=["gameDate", "home", "away"])
    for when in ("open", "close"):
        b = history.bet_results(d, when)
        calls = np.array([dashboard.call(r, True) for r in b.itertuples()])
        out = out.merge(pd.DataFrame({"gameId": b.gameId, f"ROI {when}": b.prof,
                                      f"S+1U {when}": np.where(np.isin(calls, ["SLAM", "1U"]) & (b.season >= 2021).values, b.prof, 0.0)}),
                        on="gameId", how="left")
    return out


def _sums(g):
    """Per game night: (sum, count) for every scorecard column, so a resample is a weighted sum of nights."""
    rng = {"dev 21-23": (2021, 2022), "dev 23-26": (2023, 2025)}
    cols = {}
    for c, (a, b) in rng.items():
        inside = g.season.between(a, b)
        cols[c] = (g.dev.where(inside, 0.0), 2 * inside)
        e = inside & g.early
        cols["early" + c[3:]] = (g.dev.where(e, 0.0), 2 * e)
    for c in ("LL close", "LL open", "ROI open", "ROI close"):
        cols[c] = (g[c].fillna(0.0), g[c].notna())
    for c in ("S+1U open", "S+1U close"):
        cols[c] = (g[c].fillna(0.0), pd.Series(True, index=g.index))  # a sum of units, not a mean
    night = {}
    for c, (num, cnt) in cols.items():
        f = pd.DataFrame({"n": g.gameDate, "s": num.astype(float), "k": cnt.astype(float)}).groupby("n").sum()
        night[c] = f
    return night


def noise(base_p, new_p, games, n=500, seed=0, level=0.90):
    """{column: (variant minus live, low, high)}: the difference and the middle `level` of n bootstrap resamples of game
    nights (the same nights for both, so shared luck cancels)."""
    a, b = _sums(per_game(base_p, games)), _sums(per_game(new_p, games))
    nights = sorted(set(a["dev 21-23"].index) | set(b["dev 21-23"].index))
    rs = np.random.default_rng(seed)
    w = np.stack([np.bincount(rs.integers(0, len(nights), len(nights)), minlength=len(nights)) for _ in range(n)])
    out = {}
    for c, _ in COLS:
        A, B = a[c].reindex(nights, fill_value=0.0), b[c].reindex(nights, fill_value=0.0)
        if c.startswith("S+1U"):
            stat = lambda f, ww: ww @ f.s.values
            point = B.s.sum() - A.s.sum()
        else:
            stat = lambda f, ww: (ww @ f.s.values) / np.maximum(ww @ f.k.values, 1e-9)
            point = B.s.sum() / max(B.k.sum(), 1e-9) - A.s.sum() / max(A.k.sum(), 1e-9)
        diffs = stat(B, w) - stat(A, w)
        if c.startswith("ROI"):
            diffs, point = diffs * 100, point * 100
        lo, hi = np.quantile(diffs, [(1 - level) / 2, 1 - (1 - level) / 2])
        out[c] = (float(point), float(lo), float(hi))
    return out


COLS = [("dev 21-23", "{:.5f}"), ("dev 23-26", "{:.5f}"), ("early 21-23", "{:.5f}"), ("early 23-26", "{:.5f}"),
        ("LL close", "{:.4f}"), ("LL open", "{:.4f}"), ("ROI open", "{:+.1f}%"), ("ROI close", "{:+.1f}%"),
        ("S+1U open", "{:+.1f}u"), ("S+1U close", "{:+.1f}u")]


def header(width=30):
    return f"{'variant':{width}s} " + " ".join(f"{c:>11s}" for c, _ in COLS)


def row(label, sc, width=30, base=None, ci=None):
    """One printed line; with base, accuracy columns get a '*' when better than base (lower). With ci (noise()), every
    column gets '*' (better beyond noise), '~' (within noise) or 'x' (worse beyond noise)."""
    cells = []
    for c, f in COLS:
        s = f.format(sc[c])
        if ci is not None:
            _, lo, hi = ci[c]
            good = c.startswith(("ROI", "S+1U"))  # higher is better there; lower for deviance / log loss
            s += "~" if lo <= 0 <= hi else ("*" if (lo > 0) == good else "x")
        elif base is not None and c.startswith(("dev", "early", "LL")):
            s += "*" if sc[c] < base[c] - 1e-6 else " "
        cells.append(f"{s:>11s}")
    return f"{label:{width}s} " + " ".join(cells)


def ci_row(ci, width=30):
    """The differences and their noise ranges under a row: '+0.00055 (-0.0001..+0.0012)'."""
    cells = []
    for c, f in COLS:
        d, lo, hi = ci[c]
        dec = 5 if c.startswith(("dev", "early")) else 4 if c.startswith("LL") else 1
        cells.append(f"{d:+.{dec}f}"[:11].rjust(11))
    rng = "  ".join(f"{c} {lo:+.{5 if c.startswith(('dev', 'early')) else 4 if c.startswith('LL') else 1}f}..{hi:+.{5 if c.startswith(('dev', 'early')) else 4 if c.startswith('LL') else 1}f}"
                    for c, (_, lo, hi) in ci.items())
    return f"{'  difference':{width}s} " + " ".join(cells) + f"\n{'  90% noise range':{width}s} {rng}"
