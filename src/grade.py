"""Grade the model against real closing totals (Action Network consensus).

  python3 src/grade.py
"""
import numpy as np
import pandas as pd

import model as m
import odds

ABBR = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL"}


def implied(price):
    price = np.asarray(price, float)
    return np.where(price > 0, 100 / (np.abs(price) + 100), np.abs(price) / (np.abs(price) + 100))


def payout(price):
    price = np.asarray(price, float)
    return np.where(price > 0, price / 100, 100 / np.abs(price))


def with_lines(proj, cal, path=odds.ODDS):
    """Attach closing line + model/market probabilities to each projected game."""
    o = pd.read_csv(path).dropna(subset=["total", "over", "under"])
    o = o[o.total.between(4.5, 8) & (o.over.abs() >= 100) & (o.under.abs() >= 100)]  # drop junk rows
    o["home"], o["away"] = o.home.replace(ABBR), o.away.replace(ABBR)
    o["gameDate"] = o.date.str.replace("-", "").astype(int)
    for c in ("home", "away"):  # Action Network relabels old Arizona games as Utah
        o.loc[(o[c] == "UTA") & (o.gameDate < 20240801), c] = "ARI"
    o = o.drop_duplicates(["gameDate", "home", "away"])
    d = proj.merge(o[["gameDate", "home", "away", "total", "over", "under"]].rename(columns={"total": "line"}),
                   on=["gameDate", "home", "away"])
    def p_ge(k, x):
        return m.p_from(cal, k, x)
    # model: P(over) = P(total > line), P(under) = P(total < line)
    up = np.floor(d.line).astype(int) + 1            # smallest total that goes over
    dn = np.ceil(d.line).astype(int) - 1             # largest total that goes under
    d["m_over"] = [p_ge(k, x) for k, x in zip(up, d.proj)]
    d["m_under"] = [1 - p_ge(k + 1, x) for k, x in zip(dn, d.proj)]
    io, iu = implied(d.over.values), implied(d.under.values)
    d["mkt_over"] = io / (io + iu)                   # market's fair P(over | no push), vig removed
    d["m_over_np"] = d.m_over / (d.m_over + d.m_under)
    d["result"] = np.sign(d.total - d.line)          # +1 over, -1 under, 0 push
    return d


def bets(d, edge):
    """Bet the side where model beats the vig-free market by >= edge. Returns per-bet profit."""
    over = d.m_over_np - d.mkt_over >= edge
    under = d.mkt_over - d.m_over_np >= edge
    side = np.where(over, 1, np.where(under, -1, 0))
    price = np.where(side == 1, d.over, d.under)
    prof = np.where(d.result == 0, 0.0, np.where(d.result == side, payout(price), -1.0))
    return side, pd.Series(prof[side != 0]), d.result.values[side != 0] == side[side != 0]


def report(d, label):
    dec = d[d.result != 0]
    y = (dec.result == 1).values.astype(float)
    ll = lambda p: -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    print(f"\n=== {label}: {len(d)} games with a closing line ({(d.result == 0).sum()} pushes) ===")
    print("  lines: " + ", ".join(f"{k}: {v:.0%}" for k, v in d.line.value_counts(normalize=True).sort_index().items()))
    print(f"  log loss on over/under (lower = better):  market {ll(dec.mkt_over.values):.4f}   model {ll(dec.m_over_np.values):.4f}")
    print(f"  correlation of model vs market over-probability: {np.corrcoef(d.m_over_np, d.mkt_over)[0, 1]:.2f}")
    print("  betting the side the model likes vs the vig-free market, at the actual closing price:")
    for edge in (0.0, 0.02, 0.04, 0.06, 0.08):
        side, prof, won = bets(d, edge)
        if len(prof):
            dec_ = won[prof.values != 0]
            print(f"    edge >= {edge:.0%}: {len(prof):4d} bets ({(side == 1).sum()} over / {(side == -1).sum()} under)"
                  f"  win {dec_.mean():.1%}  profit {prof.sum():+7.1f}u  ROI {prof.mean():+.1%}")


def main():
    games = m.load_games()
    proj, _, _ = m.walk(games)
    cal = m.fit_calibration(proj[proj.season.between(2022, 2023)])
    d = with_lines(proj[proj.season >= 2022], cal)
    report(d[d.season.between(2022, 2023)], "2022-23 + 2023-24 (seasons the model was tuned on)")
    test = d[d.season >= 2024]
    report(test, "2024-25 + 2025-26 (unseen test seasons)")
    # does the model add anything the market doesn't already know?
    tr = d[(d.season <= 2023) & (d.result != 0)]
    lg = lambda p: np.log(p / (1 - p))
    beta = m.logit_fit(np.column_stack([lg(tr.mkt_over), lg(tr.m_over_np)]), (tr.result == 1).values.astype(float))
    print(f"\n  blend fit on 2022-24: logit(P over) = {beta[0]:+.3f} + {beta[1]:.2f}*market + {beta[2]:.2f}*model"
          "   (model weight ~0 means it adds nothing beyond the line)")


if __name__ == "__main__":
    main()
